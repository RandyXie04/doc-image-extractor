import cv2
import numpy as np

def xywh2xyxy(x):
    # Convert nx4 boxes from [x, y, w, h] to [x1, y1, x2, y2] where xy1=top-left, xy2=bottom-right
    y = np.copy(x)
    y[..., 0] = x[..., 0] - x[..., 2] / 2  # top left x
    y[..., 1] = x[..., 1] - x[..., 3] / 2  # top left y
    y[..., 2] = x[..., 0] + x[..., 2] / 2  # bottom right x
    y[..., 3] = x[..., 1] + x[..., 3] / 2  # bottom right y
    return y

def nms(boxes, scores, iou_threshold):
    # Sort by score
    sorted_indices = np.argsort(scores)[::-1]
    keep_boxes = []
    
    while sorted_indices.size > 0:
        box_id = sorted_indices[0]
        keep_boxes.append(box_id)
        
        # Compute IoU of the picked box with the rest
        ious = compute_iou(boxes[box_id, :], boxes[sorted_indices[1:], :])
        
        # Keep boxes with IoU less than the threshold
        keep_indices = np.where(ious < iou_threshold)[0]
        sorted_indices = sorted_indices[keep_indices + 1]
        
    return keep_boxes

def compute_iou(box, boxes):
    # Compute xmin, ymin, xmax, ymax for both boxes
    xmin = np.maximum(box[0], boxes[:, 0])
    ymin = np.maximum(box[1], boxes[:, 1])
    xmax = np.minimum(box[2], boxes[:, 2])
    ymax = np.minimum(box[3], boxes[:, 3])
    
    # Compute intersection area
    intersection_area = np.maximum(0, xmax - xmin) * np.maximum(0, ymax - ymin)
    
    # Compute union area
    box_area = (box[2] - box[0]) * (box[3] - box[1])
    boxes_area = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    union_area = box_area + boxes_area - intersection_area
    
    # Compute IoU
    iou = intersection_area / union_area
    return iou

def letterbox(im, new_shape=(1280, 1280), color=(114, 114, 114)):
    # Resize and pad image while meeting stride-multiple constraints
    shape = im.shape[:2]  # current shape [height, width]
    if isinstance(new_shape, int):
        new_shape = (new_shape, new_shape)

    # Scale ratio (new / old)
    r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
    
    # Compute padding
    new_unpad = int(round(shape[1] * r)), int(round(shape[0] * r))
    dw, dh = new_shape[1] - new_unpad[0], new_shape[0] - new_unpad[1]  # wh padding
    dw /= 2  # divide padding into 2 sides
    dh /= 2

    if shape[::-1] != new_unpad:  # resize
        im = cv2.resize(im, new_unpad, interpolation=cv2.INTER_LINEAR)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    im = cv2.copyMakeBorder(im, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)  # add border
    return im, r, (dw, dh)

def postprocess(outputs, conf_threshold=0.15, iou_threshold=0.45):
    # outputs shape: (1, 6, 73101) -> (6, 73101)
    predictions = np.squeeze(outputs[0]).T  # Shape: (73101, 6)
    
    # Filter by confidence
    scores = np.max(predictions[:, 4:], axis=1)
    predictions = predictions[scores > conf_threshold, :]
    scores = scores[scores > conf_threshold]
    
    if len(scores) == 0:
        return []
    
    # Get classes
    class_ids = np.argmax(predictions[:, 4:], axis=1)
    
    # Get bounding boxes
    boxes = predictions[:, :4]
    boxes = xywh2xyxy(boxes)
    
    # Apply NMS
    indices = nms(boxes, scores, iou_threshold)
    
    results = []
    for i in indices:
        results.append({
            "box": boxes[i],
            "score": scores[i],
            "class_id": class_ids[i]
        })
        
    return results
