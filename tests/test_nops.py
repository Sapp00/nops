#!/usr/bin/env python3
"""Test suite for nops - SOPS key management tool"""

import pytest
import subprocess
import tempfile
import shutil
from pathlib import Path
import yaml


@pytest.fixture
def temp_home(tmp_path):
    """Create a temporary home directory with master key."""
    home = tmp_path / "home"
    home.mkdir()
    sops_dir = home / ".sops"
    sops_dir.mkdir()

    # Generate master key
    result = subprocess.run(
        ["age-keygen"],
        capture_output=True,
        text=True,
        check=True
    )

    # Extract private key
    for line in result.stdout.split('\n'):
        if line.startswith('AGE-SECRET-KEY-'):
            master_key = line.strip()
            break

    # Save master key
    master_key_path = sops_dir / "key.txt"
    master_key_path.write_text(master_key)

    return home


@pytest.fixture
def temp_project(tmp_path):
    """Create a temporary project directory."""
    project = tmp_path / "project"
    project.mkdir()
    return project


@pytest.fixture
def nops_env(temp_home):
    """Set up environment for nops to use temp home."""
    return {"HOME": str(temp_home)}


def run_nops(args, cwd, env):
    """Helper to run nops command."""
    # Use python -m to run nops from the module
    cmd = ["python", "-m", "nops.main"] + args
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        env={**subprocess.os.environ, **env},
        capture_output=True,
        text=True
    )
    return result


class TestNopsInit:
    """Test nops init command."""

    def test_init_creates_sops_yaml(self, temp_project, nops_env):
        """Test that init creates .sops.yaml."""
        result = run_nops(["init"], temp_project, nops_env)

        assert result.returncode == 0
        assert (temp_project / ".sops.yaml").exists()
        assert (temp_project / ".sops" / "keys.yaml").exists()

    def test_init_sops_yaml_contains_master_key(self, temp_project, nops_env, temp_home):
        """Test that .sops.yaml contains master public key."""
        # Get master public key
        master_key_path = temp_home / ".sops" / "key.txt"
        master_key = master_key_path.read_text().strip()

        result = subprocess.run(
            ["age-keygen", "-y"],
            input=master_key,
            capture_output=True,
            text=True,
            check=True
        )
        master_public_key = result.stdout.strip()

        # Run init
        run_nops(["init"], temp_project, nops_env)

        # Check .sops.yaml
        sops_yaml = temp_project / ".sops.yaml"
        config = yaml.safe_load(sops_yaml.read_text())

        assert "creation_rules" in config
        assert master_public_key in config["creation_rules"][0]["age"]

    def test_init_fails_if_already_initialized(self, temp_project, nops_env):
        """Test that init fails if .sops.yaml already exists."""
        # First init
        run_nops(["init"], temp_project, nops_env)

        # Second init should fail
        result = run_nops(["init"], temp_project, nops_env)
        assert result.returncode != 0
        assert "already exists" in result.stderr


class TestNopsCreate:
    """Test nops create command."""

    def test_create_generates_new_key(self, temp_project, nops_env):
        """Test that create generates a new key."""
        # Initialize project
        run_nops(["init"], temp_project, nops_env)

        # Create key
        result = run_nops(["create", "server1"], temp_project, nops_env)

        assert result.returncode == 0
        assert "server1" in result.stderr
        assert (temp_project / ".sops" / "keys.yaml").exists()

    def test_create_key_is_in_keys_file(self, temp_project, nops_env, temp_home):
        """Test that created key is stored in encrypted keys.yaml."""
        # Initialize and create key
        run_nops(["init"], temp_project, nops_env)
        result = run_nops(["create", "server1"], temp_project, nops_env)

        assert result.returncode == 0

        # Verify keys.yaml exists and is encrypted
        keys_file = temp_project / ".sops" / "keys.yaml"
        assert keys_file.exists()

        # Decrypt and verify server1 is in there
        master_key_path = temp_home / ".sops" / "key.txt"
        decrypt_result = subprocess.run(
            ["sops", "-d", str(keys_file)],
            capture_output=True,
            text=True,
            env={
                **subprocess.os.environ,
                "SOPS_AGE_KEY_FILE": str(master_key_path),
                "HOME": str(temp_home)
            }
        )

        assert decrypt_result.returncode == 0
        keys_data = yaml.safe_load(decrypt_result.stdout)
        assert "server1" in keys_data
        assert "private" in keys_data["server1"]
        assert "public" in keys_data["server1"]

    def test_create_encrypts_keys_file(self, temp_project, nops_env, temp_home):
        """Test that created keys are encrypted in keys.yaml."""
        # Initialize and create key
        run_nops(["init"], temp_project, nops_env)
        run_nops(["create", "server1"], temp_project, nops_env)

        keys_file = temp_project / ".sops" / "keys.yaml"
        content = keys_file.read_text()

        # Should be encrypted (contains sops metadata)
        assert "sops" in content
        assert "encrypted_regex" in content or "mac" in content

    def test_create_duplicate_key_fails(self, temp_project, nops_env):
        """Test that creating duplicate key fails."""
        run_nops(["init"], temp_project, nops_env)
        run_nops(["create", "server1"], temp_project, nops_env)

        # Try to create again
        result = run_nops(["create", "server1"], temp_project, nops_env)
        assert result.returncode != 0
        assert "already exists" in result.stderr


class TestNopsEncryptDecrypt:
    """Test encryption and decryption workflows."""

    def test_encrypt_file_with_master_key(self, temp_project, nops_env):
        """Test encrypting a file using master key."""
        # Initialize project
        run_nops(["init"], temp_project, nops_env)

        # Create a test secret file
        secret_file = temp_project / "secret.yaml"
        secret_file.write_text("password: secret123\n")

        # Encrypt it
        result = run_nops(["encrypt", "secret.yaml"], temp_project, nops_env)

        assert result.returncode == 0

        # Check file is encrypted
        content = secret_file.read_text()
        assert "sops" in content
        assert "secret123" not in content  # Plaintext should not be visible

    def test_decrypt_with_master_key(self, temp_project, nops_env, temp_home):
        """Test decrypting a file with master key."""
        # Initialize and create encrypted file
        run_nops(["init"], temp_project, nops_env)

        secret_file = temp_project / "secret.yaml"
        secret_file.write_text("password: secret123\n")
        run_nops(["encrypt", "secret.yaml"], temp_project, nops_env)

        # Decrypt using sops directly with master key
        master_key_path = temp_home / ".sops" / "key.txt"
        result = subprocess.run(
            ["sops", "-d", str(secret_file)],
            capture_output=True,
            text=True,
            env={
                **subprocess.os.environ,
                "SOPS_AGE_KEY_FILE": str(master_key_path),
                "HOME": str(temp_home)
            }
        )

        assert result.returncode == 0
        assert "password: secret123" in result.stdout

    def test_decrypt_with_generated_key(self, temp_project, nops_env, temp_home):
        """Test decrypting with a generated project key."""
        # Initialize project
        run_nops(["init"], temp_project, nops_env)

        # Create a project key
        create_result = run_nops(["create", "server1"], temp_project, nops_env)
        assert create_result.returncode == 0

        # Get server1 public key by exporting and extracting
        export_result = run_nops(["export", "server1"], temp_project, nops_env)
        assert export_result.returncode == 0

        # Extract public key from output
        server1_public = None
        for line in export_result.stdout.split('\n'):
            if line.startswith('# Public:'):
                server1_public = line.split(': ')[1].strip()
                break

        assert server1_public is not None

        # Update .sops.yaml to include server1 in creation rules
        sops_yaml = temp_project / ".sops.yaml"
        config = yaml.safe_load(sops_yaml.read_text())

        # Get master key from existing config
        master_key = config["creation_rules"][0]["age"][0]

        # Update to include both master and server1
        config["creation_rules"] = [
            {
                "path_regex": ".*",
                "age": [master_key, server1_public]
            }
        ]

        with open(sops_yaml, 'w') as f:
            yaml.dump(config, f)

        # Create and encrypt a secret
        secret_file = temp_project / "secret.yaml"
        secret_file.write_text("password: secret123\n")
        run_nops(["encrypt", "secret.yaml"], temp_project, nops_env)

        # Extract private key from export output
        server1_private = None
        for line in export_result.stdout.split('\n'):
            if line.startswith('AGE-SECRET-KEY-'):
                server1_private = line.strip()
                break

        assert server1_private is not None

        # Create temp key file for server1
        temp_key_file = temp_project / "server1.key"
        temp_key_file.write_text(server1_private)

        # Decrypt with server1 key
        result = subprocess.run(
            ["sops", "-d", str(secret_file)],
            capture_output=True,
            text=True,
            env={
                **subprocess.os.environ,
                "SOPS_AGE_KEY_FILE": str(temp_key_file),
                "HOME": str(temp_home)
            }
        )

        assert result.returncode == 0
        assert "password: secret123" in result.stdout

        # Clean up
        temp_key_file.unlink()


class TestNopsExport:
    """Test nops export command."""

    def test_export_outputs_private_key(self, temp_project, nops_env):
        """Test that export outputs the private key."""
        run_nops(["init"], temp_project, nops_env)
        run_nops(["create", "server1"], temp_project, nops_env)

        result = run_nops(["export", "server1"], temp_project, nops_env)

        assert result.returncode == 0
        assert "AGE-SECRET-KEY-" in result.stdout
        assert "server1" in result.stdout

    def test_export_nonexistent_key_fails(self, temp_project, nops_env):
        """Test that exporting non-existent key fails."""
        run_nops(["init"], temp_project, nops_env)

        result = run_nops(["export", "nonexistent"], temp_project, nops_env)

        assert result.returncode != 0
        assert "not found" in result.stderr


class TestNopsProjectRoot:
    """Test project root detection."""

    def test_finds_sops_yaml_in_parent(self, temp_project, nops_env, temp_home):
        """Test that nops finds .sops.yaml in parent directory."""
        # Initialize at root
        run_nops(["init"], temp_project, nops_env)

        # Create subdirectory
        subdir = temp_project / "deploy" / "meta"
        subdir.mkdir(parents=True)

        # Create key from subdirectory
        result = run_nops(["create", "server1"], subdir, nops_env)

        assert result.returncode == 0

        # Verify key was created in project root .sops/keys.yaml
        keys_file = temp_project / ".sops" / "keys.yaml"
        assert keys_file.exists()

        # Decrypt and verify server1 is there
        master_key_path = temp_home / ".sops" / "key.txt"
        decrypt_result = subprocess.run(
            ["sops", "-d", str(keys_file)],
            capture_output=True,
            text=True,
            env={
                **subprocess.os.environ,
                "SOPS_AGE_KEY_FILE": str(master_key_path),
                "HOME": str(temp_home)
            }
        )

        assert decrypt_result.returncode == 0
        keys_data = yaml.safe_load(decrypt_result.stdout)
        assert "server1" in keys_data

    def test_fails_without_sops_yaml(self, temp_project, nops_env):
        """Test that commands fail without .sops.yaml."""
        # Don't initialize - no .sops.yaml
        result = run_nops(["create", "server1"], temp_project, nops_env)

        assert result.returncode != 0
        assert "No .sops.yaml found" in result.stderr


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
