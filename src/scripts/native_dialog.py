import sys
import tkinter as tk
from tkinter import filedialog
import shutil
import os

def main():
    if len(sys.argv) < 3:
        return
        
    source_path = sys.argv[1]
    suggested_filename = sys.argv[2]
    
    if not os.path.exists(source_path):
        return
        
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    
    ext = suggested_filename.split(".")[-1] if "." in suggested_filename else "*"
    
    file_path = filedialog.asksaveasfilename(
        initialfile=suggested_filename,
        defaultextension=f".{ext}",
        filetypes=[(f"{ext.upper()} File", f"*.{ext}"), ("All Files", "*.*")]
    )
    
    if file_path:
        shutil.copy2(source_path, file_path)
        print(file_path)
    
if __name__ == "__main__":
    main()
