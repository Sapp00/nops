import sys
import subprocess
import hashlib
import hmac
import re
from pathlib import Path
from typing import Dict, List, Tuple
import bech32
import yaml

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

def load_config(project_root: Path) -> dict:
    """Load .sops-kdf.yaml configuration file.

    Args:
        project_root: Path to project root directory

    Returns:
        Parsed configuration dictionary
    """
    config_path = project_root / ".sops-kdf.yaml"

    if not config_path.exists():
        log("   -> ⚠️  No .sops-kdf.yaml found, using default configuration")
        return {"rules": []}

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    if not config:
        return {"rules": []}

    return config

def collect_keys_from_rules(rules: List[dict]) -> set:
    """Collect all unique key names from the rules.

    Args:
        rules: List of rule dictionaries

    Returns:
        Set of unique key names
    """
    keys = set()
    for rule in rules:
        rule_keys = rule.get('keys', [])
        keys.update(rule_keys)
    return keys

def create_sops_keys_file(keys_data: Dict[str, Tuple[str, str]], project_root: Path) -> Path:
    """Create .sops/keys.txt file with newline-separated private keys.

    Args:
        keys_data: Dictionary mapping key names to (private_key, public_key) tuples
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
        for key_name, (private_key, _) in keys_data.items():
            f.write(f"# {key_name}\n")
            f.write(f"{private_key}\n\n")

    # Set restrictive permissions (readable only by user)
    keys_file.chmod(0o600)

    log(f"   -> ✅ Created .sops/keys.txt with {len(keys_data)} key(s)")
    return keys_file

def create_sops_yaml(keys_data: Dict[str, Tuple[str, str]], rules: List[dict], project_root: Path):
    """Create .sops.yaml config file with keys and creation rules.

    Args:
        keys_data: Dictionary mapping key names to (private_key, public_key) tuples
        rules: List of rule dictionaries with path_regex and keys
        project_root: Path to project root directory
    """
    sops_yaml_path = project_root / ".sops.yaml"

    # Build YAML content manually to have proper formatting
    yaml_content = "keys:\n"

    # Add key anchors
    for key_name, (_, public_key) in keys_data.items():
        yaml_content += f"  - &{key_name} {public_key}\n"

    yaml_content += "\ncreation_rules:\n"

    if not rules:
        # Default rule: all files, all keys
        yaml_content += "  - path_regex: .*\n"
        yaml_content += "    key_groups:\n"
        yaml_content += "      - age:\n"
        for key_name in keys_data.keys():
            yaml_content += f"          - *{key_name}\n"
    else:
        # Custom rules from config
        for rule in rules:
            path_regex = rule.get('path_regex', '.*')
            rule_keys = rule.get('keys', [])

            yaml_content += f"  - path_regex: {path_regex}\n"
            yaml_content += "    key_groups:\n"
            yaml_content += "      - age:\n"

            # Always include project key first
            yaml_content += "          - *project\n"

            # Add additional keys specified in the rule
            for key_name in rule_keys:
                if key_name in keys_data and key_name != 'project':
                    yaml_content += f"          - *{key_name}\n"

    with open(sops_yaml_path, 'w') as f:
        f.write(yaml_content)

    log(f"   -> ✅ Created .sops.yaml with {len(rules) if rules else 1} rule(s)")

def run():
    log("🔐 Initializing project-scoped secrets...")

    project_root = Path.cwd()

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

    # 5. Load configuration
    config = load_config(project_root)
    rules = config.get('rules', [])

    # 6. Collect all unique key names from rules
    additional_keys = collect_keys_from_rules(rules)

    # 7. Generate project key (always included)
    keys_data = {}
    priv_key, pub_key = derive_age_key(master_key, repo_id)
    keys_data['project'] = (priv_key, pub_key)
    log(f"   -> ✅ Generated project key for: {repo_id}")

    # 8. Generate all keys referenced in rules
    for key_name in sorted(additional_keys):
        kdf_input = f"{repo_id}+{key_name}"
        priv_key, pub_key = derive_age_key(master_key, kdf_input)
        keys_data[key_name] = (priv_key, pub_key)
        log(f"   -> ✅ Generated key: {key_name}")

    # 9. Ensure .sops/ is in .gitignore
    ensure_gitignore(project_root)

    # 10. Create .sops/keys.txt with all private keys
    keys_file = create_sops_keys_file(keys_data, project_root)

    # 11. Create .sops.yaml with keys and rules
    create_sops_yaml(keys_data, rules, project_root)

    # 12. Export SOPS_AGE_KEY_FILE pointing to the keys file
    print(f"export SOPS_AGE_KEY_FILE='{keys_file.absolute()}'")

if __name__ == '__main__':
    run()
