# Contributing to SonoForge

Thank you for your interest in contributing to SonoForge! This document provides guidelines for contributing to the project.

## How to Contribute

### Reporting Issues

If you find a bug or have a feature request, please [open an issue](https://github.com/areatu/SonoForge/issues) with:

- A clear description of the problem or suggestion
- Steps to reproduce (for bugs)
- Your environment: OS, Python version, SonoForge version

### Submitting Changes

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes
4. Run tests: `python -m pytest tests/ -x`
5. Commit with a clear message
6. Push to your fork and open a Pull Request

### Code Style

- Follow [PEP 8](https://peps.python.org/pep-0008/) conventions
- Use type hints where practical
- Keep functions focused and concise
- Write docstrings for public APIs

### Testing

- Add tests for new functionality
- Ensure all tests pass before submitting
- Test on both Linux and Windows if possible

### Commit Messages

Use clear, descriptive commit messages:

```
feat(doppler): add spectral Doppler envelope tracing

fix(scroll): prevent frame decode race on fast scroll

docs(readme): update installation instructions
```

## Development Setup

```bash
# Clone and install in development mode
git clone https://github.com/areatu/SonoForge.git
cd SonoForge
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
python -m pytest tests/
```

## License

By contributing, you agree that your contributions will be licensed under the GPL-3.0 License.
