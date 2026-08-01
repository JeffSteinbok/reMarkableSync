# Building Self-Contained Executables

This guide explains how to build self-contained executables for macOS and Windows that can be distributed to non-technical users.

**Note: This tool has been tested exclusively on reMarkable 2. Compatibility with reMarkable 1 is not guaranteed.**

## Overview

The RemarkableSync project provides a unified command-line tool:
- **RemarkableSync** - Backs up files from your reMarkable tablet via USB and converts notebooks to PDF with template support

The tool can be packaged as a standalone executable that doesn't require Python installation.

## Automated Builds (Recommended for Releases)

The project includes GitHub Actions workflows that automate the entire release process, including version bumping and building executables for all platforms.

### Automated Release with Version Bump (Easiest)

1. Go to "Actions" tab in your GitHub repository
2. Select "Create Release" workflow
3. Click "Run workflow"
4. Choose version bump type:
   - `patch` (1.0.0 → 1.0.1) for bug fixes
   - `minor` (1.0.0 → 1.1.0) for new features
   - `major` (1.0.0 → 2.0.0) for breaking changes
5. Click "Run workflow"

**What happens automatically:**
- Version in `src/__version__.py` is updated and committed
- Git tag is created
- GitHub Release is created
- Executables are built for all platforms
- Build artifacts are uploaded to the release

### Manual Release Creation with Automated Builds

If you prefer to manage versions manually:

1. Update version in `src/__version__.py`
2. Create a new tag (e.g., `v1.0.0`)
3. Push the tag: `git push origin v1.0.0`
4. Create a GitHub Release with that tag
5. The build workflow automatically triggers
6. Download the artifacts from the release page:
   - `RemarkableSync-Windows.zip`
   - `RemarkableSync-macOS.zip`

### Manual Build Workflow Trigger

You can also trigger just the build workflow manually:
1. Go to "Actions" tab in your repository
2. Select "Build Executables" workflow
3. Click "Run workflow"
4. Download artifacts from the workflow run

## Manual Local Builds

If you prefer to build locally or need custom modifications, follow these instructions.

### Prerequisites

#### For Building on macOS
- macOS 10.13 or later
- Python 3.11 or higher installed
- Xcode Command Line Tools: `xcode-select --install`

#### For Building on Windows
- Windows 10 or later
- Python 3.11 or higher installed from [python.org](https://www.python.org/downloads/)
- Make sure Python is added to PATH during installation

### Building Executables

#### macOS Build

1. Clone the repository and navigate to the project directory:
   ```bash
   git clone https://github.com/JeffSteinbok/RemarkableSync.git
   cd RemarkableSync
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   pip install pyinstaller
   ```

3. Build the executable:
   ```bash
   pyinstaller RemarkableSync.spec
   ```

4. The executable will be created in the `dist/` directory:
   - `dist/RemarkableSync` or `dist/RemarkableSync.app`

#### Windows Build

1. Clone the repository and navigate to the project directory:
   ```cmd
   git clone https://github.com/JeffSteinbok/RemarkableSync.git
   cd RemarkableSync
   ```

2. Install dependencies:
   ```cmd
   pip install -r requirements.txt
   pip install pyinstaller
   ```

3. Build the executable:
   ```cmd
   pyinstaller RemarkableSync.spec
   ```

4. The executable will be created in the `dist\` directory:
   - `dist\RemarkableSync.exe`

## Testing the Executables

### macOS
```bash
# Show version
./dist/RemarkableSync --version

# Show help
./dist/RemarkableSync --help

# Test individual commands
./dist/RemarkableSync backup --help
./dist/RemarkableSync convert --help
./dist/RemarkableSync sync --help
```

### Windows
```cmd
REM Show version
dist\RemarkableSync.exe --version

REM Show help
dist\RemarkableSync.exe --help

REM Test individual commands
dist\RemarkableSync.exe backup --help
dist\RemarkableSync.exe convert --help
dist\RemarkableSync.exe sync --help
```

## Distributing to Users

### macOS Distribution

#### Option 1: ZIP Archive
1. Create a ZIP file with the executable:
   ```bash
   cd dist
   zip -r RemarkableSync-macOS.zip RemarkableSync
   ```

2. Share the ZIP file with users

#### Option 2: DMG (Recommended)
1. Create a DMG using Disk Utility or `hdiutil`
2. Include the executable and README.md
3. Users can drag the app to their Applications folder

**First Run Notice for macOS Users:**
- When running the app for the first time, macOS may show a security warning
- Users should go to System Preferences > Security & Privacy
- Click "Open Anyway" to allow the application to run

### Windows Distribution

1. Create a ZIP file with the executable:
   ```cmd
   cd dist
   powershell Compress-Archive -Path RemarkableSync.exe -DestinationPath RemarkableSync-Windows.zip
   ```

2. Share the ZIP file with users

**First Run Notice for Windows Users:**
- Windows SmartScreen may show a warning on first run
- Click "More info" then "Run anyway" to proceed
- This is normal for unsigned executables

## Usage for End Users

For detailed usage instructions, refer to the [README.md](README.md) file included with the distribution.

### Basic Usage

1. Connect your reMarkable tablet via USB
2. Run the executable:
   - **macOS**: Double-click `RemarkableSync` or run from Terminal
   - **Windows**: Double-click `RemarkableSync.exe` or run from Command Prompt

3. Default usage (backup + convert):
   ```bash
   # macOS
   ./RemarkableSync

   # Windows
   RemarkableSync.exe
   ```

4. The tool will:
   - Prompt for your reMarkable SSH password (found in Settings > Help)
   - Connect to your tablet at 10.11.99.1
   - Back up all changed files (including templates)
   - Convert notebooks updated in this backup to PDF

### Individual Commands

**Backup only:**
```bash
# macOS
./RemarkableSync backup -d ./my_backup -v

# Windows
RemarkableSync.exe backup -d .\my_backup -v
```

**Convert only:**
```bash
# macOS
./RemarkableSync convert -d ./my_backup -v

# Windows
RemarkableSync.exe convert -d .\my_backup -v
```

**Full sync with options:**
```bash
# macOS
./RemarkableSync sync --force-backup --force-convert -v

# Windows
RemarkableSync.exe sync --force-backup --force-convert -v
```

## Troubleshooting Build Issues

### PyInstaller Not Found
```bash
pip install pyinstaller
```

### Missing Dependencies
```bash
pip install -r requirements.txt
```

### Import Errors
- Check `RemarkableSync.spec` to ensure all modules are included in `hiddenimports`
- Add any missing modules from the `src/` directory structure
- Common hidden imports needed:
  - `src.backup`
  - `src.converters`
  - `src.commands`
  - `src.utils`
  - `src.template_renderer`

### Large Executable Size
- The executable includes Python runtime and all dependencies
- Typical size: 20-30 MB
- This is normal for self-contained applications with PDF rendering capabilities

### macOS Code Signing (Optional)
For professional distribution, consider signing the app:
```bash
codesign --deep --force --sign "Developer ID Application: Your Name" dist/RemarkableSync.app
```

### Windows Code Signing (Optional)
For professional distribution, consider signing the executable with a code signing certificate.

## Advanced Build Options

### Building for Different Architectures

**macOS Universal Binary:**
```bash
# Build for both Intel and Apple Silicon
pyinstaller --target-arch universal2 RemarkableSync.spec
```

**Windows 32-bit:**
- Use 32-bit Python to build 32-bit executables

### Custom Icons

1. Create icon files:
   - macOS: `.icns` file (512x512 PNG converted using `iconutil`)
   - Windows: `.ico` file (256x256 PNG converted using online tools)

2. Update the spec files:
   ```python
   icon_file = 'path/to/icon.icns'  # macOS
   icon_file = 'path/to/icon.ico'   # Windows
   ```

### Debugging Build Issues

Build with debug mode:
```bash
pyinstaller --debug all RemarkableSync.spec
```

## Clean Up

Remove build artifacts:
```bash
# macOS/Linux
rm -rf build dist *.spec

# Windows
rmdir /s /q build dist
del *.spec
```

## File Size Optimization

The default builds include everything needed to run. To reduce size:

1. Use UPX compression (already enabled in spec files)
2. Exclude unnecessary modules in the spec file
3. Use `--onefile` option for a single executable (slower startup)

## Support

For issues or questions:
- Check the main README.md for usage instructions
- Review troubleshooting_guide.md for common problems
- Open an issue on GitHub: https://github.com/JeffSteinbok/RemarkableSync/issues
