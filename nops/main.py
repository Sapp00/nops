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
    """Decrypt and load project keys from .sops/keys.yaml.

    Returns:
        Dictionary mapping key names to (private_key, public_key) tuples
    """
    keys_file = project_root / ".sops" / "keys.yaml"

    if not keys_file.exists():
        return {}

    try:
        result = subprocess.run(
            ["sops", "-d", str(keys_file)],
            capture_output=True,
            text=True,
            check=True,
            env={**subprocess.os.environ, "SOPS_AGE_KEY_FILE": str(master_key_path)}
        )
        keys_data = yaml.safe_load(result.stdout)
    except subprocess.CalledProcessError as e:
        log(f"❌ Failed to decrypt keys file: {e.stderr}")
        sys.exit(1)
    except FileNotFoundError:
        log("❌ sops command not found. Please install SOPS.")
        sys.exit(1)

    if not keys_data:
        return {}

    # Convert to dict with tuples
    keys = {}
    for key_name, key_info in keys_data.items():
        private_key = key_info['private']
        public_key = key_info['public']
        keys[key_name] = (private_key, public_key)

    return keys

def save_keys(keys: Dict[str, Tuple[str, str]], project_root: Path, master_public_key: str):
    """Encrypt and save keys to .sops/keys.yaml using SOPS."""
    sops_dir = project_root / ".sops"
    sops_dir.mkdir(exist_ok=True)

    keys_file = sops_dir / "keys.yaml"

    # Build keys structure
    keys_dict = {}
    for key_name, (private_key, public_key) in sorted(keys.items()):
        keys_dict[key_name] = {
            'private': private_key,
            'public': public_key
        }

    # Create temporary .sops.yaml for encrypting keys.yaml
    temp_sops_yaml = sops_dir / ".sops.yaml"
    temp_sops_config = {
        "creation_rules": [
            {
                "path_regex": "keys\\.yaml$",
                "key_groups": [
                    {
                        "age": [master_public_key]
                    }
                ]
            }
        ]
    }

    try:
        # Write temp SOPS config
        with open(temp_sops_yaml, 'w') as f:
            yaml.dump(temp_sops_config, f, default_flow_style=False, sort_keys=False)

        # Write plaintext keys
        with open(keys_file, 'w') as f:
            yaml.dump(keys_dict, f, default_flow_style=False, sort_keys=False)

        # Encrypt with SOPS using temp config (use absolute paths)
        subprocess.run(
            ["sops", "--config", str(temp_sops_yaml.resolve()), "-e", "-i", str(keys_file.resolve())],
            check=True
        )

        # Clean up temp config
        temp_sops_yaml.unlink()

    except subprocess.CalledProcessError as e:
        log(f"❌ Failed to encrypt keys file: {e.stderr}")
        if temp_sops_yaml.exists():
            temp_sops_yaml.unlink()
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

    keys = load_keys(project_root, master_key_path)

    if key_name in keys:
        log(f"❌ Key '{key_name}' already exists")
        sys.exit(1)

    log(f"🔑 Generating key '{key_name}'...")
    private_key, public_key = generate_age_key()
    keys[key_name] = (private_key, public_key)

    save_keys(keys, project_root, master_public_key)

    log(f"✅ Key '{key_name}' created")
    log(f"   Public key: {public_key}")
    log(f"   Encrypted in .sops/keys.yaml")
    log(f"   Add '{public_key}' to creation_rules in .sops.yaml to use it")

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

def is_sops_encrypted(file_path: Path, master_key_path: Path) -> bool:
    """Check if a file is SOPS encrypted by attempting to decrypt it."""
    try:
        subprocess.run(
            ["sops", "-d", str(file_path)],
            env={**subprocess.os.environ, "SOPS_AGE_KEY_FILE": str(master_key_path)},
            capture_output=True,
            check=True
        )
        return True
    except subprocess.CalledProcessError:
        return False
    except FileNotFoundError:
        return False

def cmd_updatekeys(args):
    """Update keys for all SOPS-encrypted files in a directory."""
    path = Path(args.path if args.path else '.').resolve()
    master_key_path = Path.home() / ".sops" / "key.txt"
    project_root = find_project_root(path if path.is_dir() else path.parent)

    if not path.exists():
        log(f"❌ Path not found: {path}")
        sys.exit(1)

    # Collect files to update
    files_to_update = []
    keys_yaml_path = project_root / ".sops" / "keys.yaml"

    if path.is_file():
        if is_sops_encrypted(path, master_key_path):
            files_to_update.append(path)
    else:
        # Recursively find all SOPS-encrypted files
        for file_path in path.rglob('*'):
            # Skip .sops/keys.yaml as it's managed internally by nops
            if file_path == keys_yaml_path:
                continue
            if file_path.is_file() and is_sops_encrypted(file_path, master_key_path):
                files_to_update.append(file_path)

    if not files_to_update:
        log(f"❌ No SOPS-encrypted files found in {path}")
        sys.exit(0)

    # Show files to user
    log(f"🔄 Found {len(files_to_update)} encrypted file(s):")
    for file_path in files_to_update:
        relative_path = file_path.relative_to(project_root)
        log(f"   - {relative_path}")
    log("")

    # Run sops updatekeys - it will show diffs and ask for confirmation (unless -y flag)
    try:
        cmd = ["sops", "updatekeys"]
        if args.yes:
            cmd.append("-y")
        cmd.extend([str(f) for f in files_to_update])

        subprocess.run(
            cmd,
            env={**subprocess.os.environ, "SOPS_AGE_KEY_FILE": str(master_key_path)},
            check=True
        )

        # Print success message
        log(f"✅ Successfully updated {len(files_to_update)} file(s)")
    except subprocess.CalledProcessError:
        sys.exit(1)
    except FileNotFoundError:
        log("❌ sops command not found. Please install SOPS.")
        sys.exit(1)

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
    # Simple format that SOPS can parse correctly
    sops_config = {
        "creation_rules": [
            {
                "path_regex": ".*",
                "age": [master_public_key]
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
  nops updatekeys secrets/     # Update keys for all encrypted files
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
    parser_encrypt.add_argument('file_arg', help='File to encrypt')
    parser_encrypt.set_defaults(func=cmd_encrypt)

    # export command
    parser_export = subparsers.add_parser('export', help='Export a key')
    parser_export.add_argument('name', help='Key name to export')
    parser_export.set_defaults(func=cmd_export)

    # updatekeys command
    parser_updatekeys = subparsers.add_parser('updatekeys', help='Update keys for encrypted files')
    parser_updatekeys.add_argument('path', nargs='?', help='File or directory to update (default: current directory)')
    parser_updatekeys.add_argument('-y', '--yes', action='store_true', help='Auto-confirm without showing diffs')
    parser_updatekeys.set_defaults(func=cmd_updatekeys)

    # Default command: edit file
    parser.add_argument('file', nargs='?', help='File to edit with SOPS')

    args = parser.parse_args()

    if args.command:
        # Handle subcommands
        if args.command == 'encrypt':
            # Rename file_arg to file for consistency
            args.file = args.file_arg
        args.func(args)
    elif hasattr(args, 'file') and args.file:
        # Default: edit file
        cmd_edit(args)
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == '__main__':
    run()
