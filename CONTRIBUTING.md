# Contributing to RemarkableSync

Thank you for your interest in contributing to RemarkableSync! This document provides guidelines and information for contributors.

## Getting Started

### Development Setup

1. **Fork and clone the repository:**
   ```bash
   git clone https://github.com/YOUR_USERNAME/RemarkableSync.git
   cd RemarkableSync
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```

4. **Run the tool in development mode:**
   ```bash
   python RemarkableSync.py --help
   ```

## Development Guidelines

### Code Style

This project uses:
- **Black** for code formatting (line length: 100)
- **Ruff** for linting
- **isort** for import sorting

Format your code before committing:
```bash
black .
ruff check --fix .
isort .
```

### Type Hints

Use type hints for all function parameters and return values where possible. The project targets Python 3.11+.

### Testing

Run tests before submitting pull requests:
```bash
pytest
```

For coverage reports:
```bash
pytest --cov=src
```

## Making Changes

### Branch Strategy

1. Create a feature branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. Make your changes and commit with clear messages:
   ```bash
   git commit -m "Add feature: description of changes"
   ```

3. Push to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```

4. Open a Pull Request against the `main` branch

### Commit Messages

- Use clear, descriptive commit messages
- Start with a verb (Add, Fix, Update, Remove, etc.)
- Keep the first line under 72 characters
- Add details in the body if needed

Examples:
- `Add support for v7 notebook format`
- `Fix template rendering issue on Windows`
- `Update dependencies to latest versions`

## Pull Request Process

1. **Ensure your code passes all checks:**
   - Code is formatted with Black
   - No linting errors from Ruff
   - All tests pass
   - Type hints are present where appropriate

2. **Update documentation:**
   - Update README.md if adding features
   - Add docstrings to new functions/classes
   - Update RECENT_CHANGES.md if applicable

3. **Describe your changes:**
   - Explain what the PR does and why
   - Reference any related issues
   - Include screenshots for UI changes

4. **Wait for review:**
   - Address any feedback from maintainers
   - Be patient and responsive to comments

## Project Structure

```
RemarkableSync/
├── src/
│   ├── backup/         # SSH connection and backup logic
│   ├── commands/       # CLI command implementations
│   ├── converters/     # PDF conversion (v4, v5, v6 formats)
│   └── utils/          # Utility functions
├── tests/              # Test files
├── release/            # Release and distribution documentation
└── RemarkableSync.py   # Main entry point
```

## Building Executables

To build standalone executables for distribution, see [release/BUILD_EXECUTABLES.md](release/BUILD_EXECUTABLES.md).

## Release Process

Releases are managed by maintainers. The process is documented in [release/RELEASE_CHECKLIST.md](release/RELEASE_CHECKLIST.md).

## Areas for Contribution

We welcome contributions in these areas:

### Features
- Support for new reMarkable file formats
- Additional export formats (SVG, PNG, etc.)
- Cloud sync integration
- GUI/web interface

### Bug Fixes
- Connection stability improvements
- Template rendering accuracy
- Cross-platform compatibility issues

### Documentation
- Usage examples and tutorials
- Troubleshooting guides
- Translation to other languages

### Testing
- Unit test coverage
- Integration tests
- Testing on reMarkable 1 devices

## Getting Help

- **Issues**: Check [existing issues](https://github.com/JeffSteinbok/RemarkableSync/issues) or open a new one
- **Discussions**: Use GitHub Discussions for questions and ideas
- **Documentation**: See [README.md](README.md) and files in `release/`

## Code of Conduct

- Be respectful and constructive
- Welcome newcomers and help them learn
- Focus on what is best for the community
- Show empathy towards other contributors

## License

By contributing to RemarkableSync, you agree that your contributions will be licensed under the MIT License.

## Questions?

Feel free to open an issue or discussion if you have questions about contributing!
