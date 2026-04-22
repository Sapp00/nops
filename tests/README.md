# nops Test Suite

## Running Tests

```bash
# Install dependencies
poetry install

# Run all tests
poetry run pytest tests/

# Run with verbose output
poetry run pytest tests/ -v

# Run specific test class
poetry run pytest tests/test_nops.py::TestNopsEncryptDecrypt -v

# Run with coverage
poetry run pytest tests/ --cov=nops
```

## Test Structure

- `test_nops.py` - Main test suite
  - `TestNopsInit` - Tests for project initialization
  - `TestNopsCreate` - Tests for key creation
  - `TestNopsEncryptDecrypt` - Tests for encryption/decryption workflows
  - `TestNopsExport` - Tests for key export
  - `TestNopsProjectRoot` - Tests for project root detection

## Fixtures

- `temp_home` - Temporary home directory with generated master key
- `temp_project` - Temporary project directory
- `nops_env` - Environment variables for isolated testing

## Requirements

- `age` - Age encryption tool
- `sops` - Mozilla SOPS
- `pytest` - Testing framework
