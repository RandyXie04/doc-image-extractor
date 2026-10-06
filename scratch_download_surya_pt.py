import os
import shutil
from pathlib import Path
from huggingface_hub import snapshot_download

def main():
    base_dir = Path("models/surya_pt")
    base_dir.mkdir(parents=True, exist_ok=True)
    
    models_to_download = {
        "det": "vikp/surya_det",
        "rec": "vikp/surya_rec",
        "layout": "vikp/surya_layout",
        "order": "vikp/surya_order"
    }
    
    print("開始下載/複製 PyTorch 模型到 models/surya_pt/ ...")
    
    for folder_name, repo_id in models_to_download.items():
        dest_path = base_dir / folder_name
        print(f"正在處理 {repo_id} -> {dest_path} ...")
        # snapshot_download automatically uses cache if available and symlinks or copies
        snapshot_download(
            repo_id=repo_id,
            local_dir=dest_path,
            local_dir_use_symlinks=False, # We want actual files so we can zip them
            ignore_patterns=["*.onnx", "*.safetensors.onnx", "*.msgpack"]
        )
        print(f"{repo_id} 完成！")
        
    print("所有模型下載/複製完成！")
    
    # 壓縮為 zip
    zip_path = Path("models/surya_pt.zip")
    print(f"開始將 {base_dir} 壓縮為 {zip_path} (這可能需要幾分鐘)...")
    shutil.make_archive(str(zip_path.with_suffix("")), 'zip', base_dir)
    print(f"壓縮完成！您現在可以將 {zip_path} 上傳至 GitHub Releases。")
    print("上傳完成後，您可以刪除 models/surya_pt 資料夾，僅保留 zip 備份。")

if __name__ == "__main__":
    main()
