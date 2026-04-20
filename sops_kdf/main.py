import sys
import subprocess
import hashlib
import hmac
import re
import argparse
from pathlib import Path
import bech32

def log(msg):
    print(msg, file=sys.stderr)

def derive_age_key(master_key: str, kdf_input: str) -> tuple[str, str]:
    """Derive an age key pair from master key and KDF input.

    Returns:
        tuple: (private_key, public_key)
    """
    ikm = master_key.encode()
    info = kdf_input.encode()

    prk = hmac.new(b'age-kdf-salt', ikm, hashlib.sha256).digest()
    okm = hmac.new(prk, info + bytes([1]), hashlib.sha256).digest()

    data = bech32.convertbits(okm, 8, 5)
    derived_key = bech32.bech32_encode('age-secret-key-', data).upper()

    # Derive the Public Key automatically
    try:
        process = subprocess.run(
            ["age-keygen", "-y"],
            input=derived_key,
            capture_output=True,
            text=True,
            check=True
        )
        public_key = process.stdout.strip()
    except subprocess.CalledProcessError as e:
        log(f"   -> ⚠️ Failed to derive public key: {e.stderr}")
        sys.exit(1)

    return derived_key, public_key

def ensure_gitignore(project_root: Path):
    """Ensure .sops/ directory is in .gitignore."""
    gitignore_path = project_root / ".gitignore"
    sops_entry = ".sops/"

    # Read existing .gitignore if it exists
    existing_lines = []
    if gitignore_path.exists():
        with open(gitignore_path, 'r') as f:
            existing_lines = f.read().splitlines()

    # Check if .sops/ is already ignored
    if sops_entry in existing_lines or ".sops" in existing_lines:
        return

    # Add .sops/ to .gitignore
    with open(gitignore_path, 'a') as f:
        if existing_lines and existing_lines[-1]:
            # Add newline before if file doesn't end with one
            f.write('\n')
        f.write(f'{sops_entry}\n')

    log(f"   -> ✅ Added .sops/ to .gitignore")

def create_sops_keys_file(private_keys: list[str], project_root: Path) -> Path:
    """Create .sops/keys.txt file with newline-separated private keys.

    Args:
        private_keys: List of private age keys
        project_root: Path to project root directory

    Returns:
        Path to the created keys file
    """
    sops_dir = project_root / ".sops"
    sops_dir.mkdir(exist_ok=True)

    keys_file = sops_dir / "keys.txt"
    with open(keys_file, 'w') as f:
        f.write("# Auto-generated age keys for SOPS\n")
        f.write("# DO NOT COMMIT THIS FILE\n\n")
        for key in private_keys:
            f.write(f"{key}\n")

    # Set restrictive permissions (readable only by user)
    keys_file.chmod(0o600)

    log(f"   -> ✅ Created .sops/keys.txt with {len(private_keys)} key(s)")
    return keys_file

def create_sops_yaml(public_keys: list[str], project_root: Path):
    """Create .sops.yaml config file with the given public keys.

    Args:
        public_keys: List of public age keys
        project_root: Path to project root directory
    """
    sops_yaml_path = project_root / ".sops.yaml"

    # Build the YAML content with comma-separated public keys
    yaml_content = "creation_rules:\n"
    yaml_content += "  - path_regex: .*\n"
    yaml_content += "    age: "
    yaml_content += ','.join(public_keys)
    yaml_content += '\n'

    with open(sops_yaml_path, 'w') as f:
        f.write(yaml_content)

    log(f"   -> ✅ Created .sops.yaml with {len(public_keys)} recipient(s)")

def run():
    parser = argparse.ArgumentParser(description='Generate SOPS age keys using KDF')
    parser.add_argument('suffixes', nargs='*', help='Additional suffixes for KDF (e.g., staging prod)')
    args = parser.parse_args()

    log("🔐 Initializing project-scoped secrets...")

    # 1. Check for Git repo
    if not Path(".git").is_dir():
        log("   -> ⚠️  No .git directory found. Run inside a git repository.")
        sys.exit(0)

    # 2. Get remote URL via subprocess
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            capture_output=True, text=True, check=True
        )
        remote_url = result.stdout.strip()
    except subprocess.CalledProcessError:
        log("   -> ⚠️  No remote.origin.url found in git config.")
        sys.exit(0)

    if not remote_url:
        log("   -> ⚠️  No remote.origin.url found.")
        sys.exit(0)

    # 3. Extract Repo ID (the Salt)
    match = re.search(r'[:/]([^/]+/[^/]+?)(?:\.git)?$', remote_url)
    if not match:
        log(f"   -> ⚠️  Could not parse repository ID from {remote_url}")
        sys.exit(0)

    repo_id = match.group(1)

    # 4. Load Master Key
    master_key_path = Path.home() / ".sops" / "key.txt"
    if not master_key_path.is_file():
        log(f"   -> ⚠️  Missing master key at {master_key_path}")
        sys.exit(0)

    with open(master_key_path, "r") as f:
        master_key = None
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                master_key = line
                break

    if not master_key:
        log(f"   -> ⚠️  No valid key found in {master_key_path}")
        sys.exit(0)

    # 5. Build list of KDF inputs: [repo_id, repo_id+suffix1, repo_id+suffix2, ...]
    kdf_inputs = [repo_id]
    if args.suffixes:
        for suffix in args.suffixes:
            kdf_inputs.append(f"{repo_id}+{suffix}")

    # 6. Generate all key pairs
    private_keys = []
    public_keys = []

    for kdf_input in kdf_inputs:
        priv_key, pub_key = derive_age_key(master_key, kdf_input)
        private_keys.append(priv_key)
        public_keys.append(pub_key)
        log(f"   -> ✅ Generated key for: {kdf_input}")

    project_root = Path.cwd()

    # 7. Ensure .sops/ is in .gitignore
    ensure_gitignore(project_root)

    # 8. Create .sops/keys.txt with all private keys
    keys_file = create_sops_keys_file(private_keys, project_root)

    # 9. Create .sops.yaml with all public keys
    create_sops_yaml(public_keys, project_root)

    # 10. Export SOPS_AGE_KEY_FILE pointing to the keys file
    print(f"export SOPS_AGE_KEY_FILE='{keys_file.absolute()}'")

if __name__ == '__main__':
    run()
