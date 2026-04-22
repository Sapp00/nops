#!/usr/bin/env python3
"""nops - Simple SOPS key management tool"""

import sys
import subprocess
import argparse
from pathlib import Path
from typing import Dict, Tuple, Optional
import yaml

def log(msg):
    """Print message to stderr."""
    print(msg, file=sys.stderr)

def find_project_root(start_path: Optional[Path] = None) -> Path:
    """Find project root by looking for .sops.yaml.

    Traverses up the directory tree from start_path until finding .sops.yaml or reaching /.

    Args:
        start_path: Directory to start searching from (defaults to cwd)

    Returns:
        Path to project root

    Raises:
        SystemExit if no .sops.yaml found
    """
    current = start_path or Path.cwd()
    current = current.resolve()

    while True:
        sops_yaml = current / ".sops.yaml"
        if sops_yaml.exists():
            return current

        if current == current.parent:  # Reached root
            log("❌ No .sops.yaml found in current directory or any parent directory")
            log("   Run 'nops init' to create a new project")
            sys.exit(1)

        current = current.parent

def get_master_key() -> str:
    """Load master key from ~/.sops/key.txt.

    Returns:
        Master key string
    """
    master_key_path = Path.home() / ".sops" / "key.txt"
    if not master_key_path.is_file():
        log(f"❌ Missing master key at {master_key_path}")
        log(f"   Generate one with: age-keygen -o {master_key_path}")
        sys.exit(1)

    with open(master_key_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                return line

    log(f"❌ No valid key found in {master_key_path}")
    sys.exit(1)

def generate_age_key() -> Tuple[str, str]:
    """Generate a fresh age key pair using age-keygen.

    Returns:
        tuple: (private_key, public_key)
    """
    try:
        result = subprocess.run(
            ["age-keygen"],
            capture_output=True,
            text=True,
            check=True
        )

        # Parse output
        lines = result.stdout.strip().split('\n')
        public_key = None
        private_key = None

        for line in lines:
            if line.startswith('# public key:'):
                public_key = line.split(': ')[1].strip()
            elif line.startswith('AGE-SECRET-KEY-'):
                private_key = line.strip()

        if not private_key or not public_key:
            log("❌ Failed to parse age-keygen output")
            sys.exit(1)

        return private_key, public_key

    except subprocess.CalledProcessError as e:
        log(f"❌ Failed to generate age key: {e.stderr}")
        sys.exit(1)
    except FileNotFoundError:
        log("❌ age-keygen not found. Please install age.")
        sys.exit(1)

def get_master_public_key(master_key: str) -> str:
    """Get public key from master private key."""
    try:
        result = subprocess.run(
            ["age-keygen", "-y"],
            input=master_key,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        log(f"❌ Failed to get master public key: {e.stderr}")
        sys.exit(1)

def load_keys(project_root: Path, master_key_path: Path) -> Dict[str, Tuple[str, str]]:
    """Decrypt and load project keys from .sops/keys.txt.age.

    Returns:
        Dictionary mapping key names to (private_key, public_key) tuples
    """
    keys_file_encrypted = project_root / ".sops" / "keys.txt.age"

    if not keys_file_encrypted.exists():
        return {}

    try:
        result = subprocess.run(
            ["age", "-d", "-i", str(master_key_path), str(keys_file_encrypted)],
            capture_output=True,
            text=True,
            check=True
        )
        keys_content = result.stdout
    except subprocess.CalledProcessError as e:
        log(f"❌ Failed to decrypt keys file: {e.stderr}")
        sys.exit(1)
    except FileNotFoundError:
        log("❌ age command not found. Please install age.")
        sys.exit(1)

    # Parse keys file
    keys = {}
    current_key_name = None
    for line in keys_content.split('\n'):
        line = line.strip()
        if line.startswith('# ') and not line.startswith('# SOPS') and not line.startswith('# DO NOT'):
            current_key_name = line[2:].strip()
        elif line.startswith('AGE-SECRET-KEY-'):
            private_key = line
            # Derive public key
            try:
                result = subprocess.run(
                    ["age-keygen", "-y"],
                    input=private_key,
                    capture_output=True,
                    text=True,
                    check=True
                )
                public_key = result.stdout.strip()
                if current_key_name:
                    keys[current_key_name] = (private_key, public_key)
                current_key_name = None
            except subprocess.CalledProcessError:
                continue

    return keys

def save_keys(keys: Dict[str, Tuple[str, str]], project_root: Path, master_public_key: str):
    """Encrypt and save keys to .sops/keys.txt.age."""
    sops_dir = project_root / ".sops"
    sops_dir.mkdir(exist_ok=True)

    # Build keys content
    keys_content = "# SOPS Keys - Auto-managed by nops\n"
    keys_content += "# DO NOT EDIT MANUALLY\n\n"

    for key_name, (private_key, _) in sorted(keys.items()):
        keys_content += f"# {key_name}\n"
        keys_content += f"{private_key}\n\n"

    # Encrypt with age
    keys_file_encrypted = sops_dir / "keys.txt.age"
    try:
        subprocess.run(
            ["age", "-r", master_public_key, "-o", str(keys_file_encrypted)],
            input=keys_content,
            capture_output=True,
            text=True,
            check=True
        )
    except subprocess.CalledProcessError as e:
        log(f"❌ Failed to encrypt keys file: {e.stderr}")
        sys.exit(1)

def load_sops_yaml(project_root: Path) -> dict:
    """Load .sops.yaml configuration."""
    sops_yaml_path = project_root / ".sops.yaml"

    if not sops_yaml_path.exists():
        return {"keys": [], "creation_rules": []}

    with open(sops_yaml_path, 'r') as f:
        content = yaml.safe_load(f)

    return content or {"keys": [], "creation_rules": []}

def save_sops_yaml(config: dict, project_root: Path):
    """Save .sops.yaml configuration."""
    sops_yaml_path = project_root / ".sops.yaml"

    with open(sops_yaml_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

def cmd_create(args):
    """Create a new project key."""
    key_name = args.name
    project_root = find_project_root()
    master_key_path = Path.home() / ".sops" / "key.txt"
    master_key = get_master_key()
    master_public_key = get_master_public_key(master_key)

    # Load existing keys
    keys = load_keys(project_root, master_key_path)

    if key_name in keys:
        log(f"❌ Key '{key_name}' already exists")
        sys.exit(1)

    # Generate new key
    log(f"🔑 Generating key '{key_name}'...")
    private_key, public_key = generate_age_key()
    keys[key_name] = (private_key, public_key)

    # Save encrypted keys
    save_keys(keys, project_root, master_public_key)

    # Update .sops.yaml - add key as anchor
    sops_config = load_sops_yaml(project_root)

    # Add to keys section (with YAML anchor)
    if "keys" not in sops_config:
        sops_config["keys"] = []

    # Check if key already exists in YAML
    key_exists = any(
        isinstance(k, dict) and k.get(key_name) == public_key
        for k in sops_config["keys"]
    )

    if not key_exists:
        sops_config["keys"].append({key_name: public_key})

    save_sops_yaml(sops_config, project_root)

    log(f"✅ Key '{key_name}' created")
    log(f"   Public key: {public_key}")
    log(f"   Add this key to creation_rules in .sops.yaml to use it")

def cmd_edit(args):
    """Edit a secret file with SOPS."""
    file_path = Path(args.file).resolve()
    master_key_path = Path.home() / ".sops" / "key.txt"

    if not file_path.exists():
        log(f"❌ File not found: {file_path}")
        sys.exit(1)

    # Run SOPS with master key
    try:
        subprocess.run(
            ["sops", str(file_path)],
            env={**subprocess.os.environ, "SOPS_AGE_KEY_FILE": str(master_key_path)},
            check=True
        )
    except subprocess.CalledProcessError:
        sys.exit(1)
    except FileNotFoundError:
        log("❌ sops command not found. Please install SOPS.")
        sys.exit(1)

def cmd_encrypt(args):
    """Encrypt a file with SOPS."""
    file_path = Path(args.file).resolve()
    project_root = find_project_root(file_path.parent)

    if not file_path.exists():
        log(f"❌ File not found: {file_path}")
        sys.exit(1)

    # Run SOPS encrypt
    try:
        subprocess.run(
            ["sops", "-e", "-i", str(file_path)],
            check=True
        )
        log(f"✅ Encrypted {file_path}")
    except subprocess.CalledProcessError:
        sys.exit(1)
    except FileNotFoundError:
        log("❌ sops command not found. Please install SOPS.")
        sys.exit(1)

def cmd_export(args):
    """Export a specific key for deployment."""
    key_name = args.name
    project_root = find_project_root()
    master_key_path = Path.home() / ".sops" / "key.txt"

    # Load keys
    keys = load_keys(project_root, master_key_path)

    if key_name not in keys:
        log(f"❌ Key '{key_name}' not found")
        log(f"   Available keys: {', '.join(keys.keys())}")
        sys.exit(1)

    private_key, public_key = keys[key_name]

    print(f"# Key: {key_name}")
    print(f"# Public: {public_key}")
    print(private_key)

def cmd_init(args):
    """Initialize a new nops project."""
    project_root = Path.cwd()
    sops_yaml = project_root / ".sops.yaml"

    if sops_yaml.exists():
        log(f"❌ .sops.yaml already exists at {sops_yaml}")
        sys.exit(1)

    master_key_path = Path.home() / ".sops" / "key.txt"
    master_key = get_master_key()
    master_public_key = get_master_public_key(master_key)

    # Create minimal .sops.yaml with master key
    sops_config = {
        "keys": [
            {"master": master_public_key}
        ],
        "creation_rules": [
            {
                "path_regex": ".*",
                "key_groups": [
                    {
                        "age": [
                            {"master": None}  # Will be replaced with anchor
                        ]
                    }
                ]
            }
        ]
    }

    # Create .sops directory
    sops_dir = project_root / ".sops"
    sops_dir.mkdir(exist_ok=True)

    # Save initial empty keys file
    save_keys({}, project_root, master_public_key)

    # Save .sops.yaml
    save_sops_yaml(sops_config, project_root)

    log(f"✅ Initialized nops project at {project_root}")
    log(f"   Created .sops.yaml with master key")
    log(f"   Run 'nops create <name>' to add more keys")

def run():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="nops - Simple SOPS key management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  nops init                    # Initialize new project
  nops create server1          # Create new key 'server1'
  nops secrets/prod.yaml       # Edit encrypted file
  nops encrypt secrets/new.yaml # Encrypt a file
  nops export server1          # Export key for deployment
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # init command
    parser_init = subparsers.add_parser('init', help='Initialize new nops project')
    parser_init.set_defaults(func=cmd_init)

    # create command
    parser_create = subparsers.add_parser('create', help='Create a new key')
    parser_create.add_argument('name', help='Key name')
    parser_create.set_defaults(func=cmd_create)

    # encrypt command
    parser_encrypt = subparsers.add_parser('encrypt', help='Encrypt a file')
    parser_encrypt.add_argument('file', help='File to encrypt')
    parser_encrypt.set_defaults(func=cmd_encrypt)

    # export command
    parser_export = subparsers.add_parser('export', help='Export a key')
    parser_export.add_argument('name', help='Key name to export')
    parser_export.set_defaults(func=cmd_export)

    # Default command: edit file
    parser.add_argument('file', nargs='?', help='File to edit with SOPS')

    args = parser.parse_args()

    if args.command:
        args.func(args)
    elif args.file:
        # Default: edit file
        args.func = cmd_edit
        args.func(args)
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == '__main__':
    run()
