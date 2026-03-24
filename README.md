# PathDrill

**⚠️ This project was developed as an experimental and rapid prototyping effort, focusing on performance and usability.**

**A fast and efficient file path extraction and hierarchy mapping tool for Windows.**

Built with Python and PySide6.

PathDrill is designed to explore and analyze complex directory structures with ease. It allows you to scan folders deeply, extract useful metadata (such as file size, modification date, and extensions), and export everything into a clean, structured JSON format.

Under the hood, it uses `os.scandir` for high-performance traversal, making it capable of handling thousands of nested directories without significant memory overhead.

---

## ✨ Features

* **Built-in File Explorer**
  Navigate your filesystem through a fast and responsive interface with full access to local drives.

* **Deep Directory Scanning**
  Efficient multi-threading ensures smooth performance, even when working with large and deeply nested folders.

* **Adjustable Scan Depth**
  Control how deep the scan goes to avoid unnecessary processing.

* **Structured JSON Export**
  Export the full directory tree with:

  * ISO 8601 formatted timestamps
  * Human-readable file sizes
  * Raw byte data for precision

---

## 📸 Screenshot


![PathDrill Screenshot](assets/screenshot.jpg)

---

## 🧪 Example Output

```json
{
    "report_info": {
        "tool": "PathDrill-Extractor",
        "creation_datetime": "2026-03-24T22:54:04.782642",
        "scanned_paths_count": 1,
        "defined_depth": "Unlimited",
        "metadata_filtering": {
            "include_path": true,
            "include_date": true,
            "include_bytes": true,
            "include_readable": true,
            "include_extension": true
        },
        "status": "Completed Successfully"
    },
    "scan_results": [
        {
            "name": "X",
            "full_path": "C:/X",
            "last_modified": "2026-03-24T22:07:33.654003",
            "size_bytes": 0,
            "size_readable": "0 B",
            "type": "directory",
            "contents": [
                {
                    "name": "Y1",
                    "full_path": "C:/X/Y1",
                    "last_modified": "2026-03-24T22:08:15.178289",
                    "size_bytes": 0,
                    "size_readable": "0 B",
                    "type": "directory",
                    "contents": [
                        {
                            "name": "aAA.txt",
                            "full_path": "C:/X/Y1/aAA.txt",
                            "last_modified": "2026-03-24T22:08:11.743058",
                            "size_bytes": 0,
                            "size_readable": "0 B",
                            "type": "file",
                            "extension": ".txt"
                        }
                    ]
                },
                {
                    "name": "Y2",
                    "full_path": "C:/X/Y2",
                    "last_modified": "2026-03-24T22:08:04.905914",
                    "size_bytes": 0,
                    "size_readable": "0 B",
                    "type": "directory",
                    "contents": [
                        {
                            "name": "zZZ.txt",
                            "full_path": "C:/X/Y2/zZZ.txt",
                            "last_modified": "2026-03-24T22:07:55.695189",
                            "size_bytes": 0,
                            "size_readable": "0 B",
                            "type": "file",
                            "extension": ".txt"
                        }
                    ]
                }
            ]
        }
    ]
}
```
---

## 🚀 Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/Bedirhan-thinking/PathDrill.git
cd PathDrill
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the application

```bash
python PathDrill.py
```

---

## 📦 Building a Standalone Executable

You can package PathDrill into a single `.exe` file using PyInstaller:

```bash
pip install pyinstaller
pyinstaller --noconsole --onefile --icon=icon.ico PathDrill.py
```

The compiled executable will be available in the `dist` directory.

---

## 🤝 Contributing

Contributions, ideas, and feedback are always welcome.
Feel free to open an issue or submit a pull request.
