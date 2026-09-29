import os
from huggingface_hub import snapshot_download

def download_models():
    print("Downloading vikp/surya_det3...")
    snapshot_download(repo_id="vikp/surya_det3", local_dir="./models/surya_det3")
    
    print("Downloading vikp/surya_rec2...")
    snapshot_download(repo_id="vikp/surya_rec2", local_dir="./models/surya_rec2")
    
    print("Downloading vikp/surya_layout2...")
    snapshot_download(repo_id="vikp/surya_layout2", local_dir="./models/surya_layout2")
    
    print("Downloading vikp/surya_order...")
    snapshot_download(repo_id="vikp/surya_order", local_dir="./models/surya_order")
    
    print("Downloading vikp/surya_tablerec...")
    snapshot_download(repo_id="vikp/surya_tablerec", local_dir="./models/surya_tablerec")
    
    print("All models downloaded successfully.")

if __name__ == "__main__":
    download_models()
