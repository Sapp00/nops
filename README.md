# nix-sops-kdf

Deterministic SOPS age key derivation for project-scoped secrets using HKDF (HMAC-based Key Derivation Function).

## Overview

This tool automatically derives project-specific age encryption keys from a single master key using HKDF. It eliminates the need to manage separate age keys for each project while maintaining cryptographic isolation between repositories.

### Key Features

- **Deterministic key derivation**: Same master key + same repo = same derived keys
- **Multiple keys per project**: Support for environment-specific keys (staging, production, etc.)
- **Automatic SOPS configuration**: Generates `.sops.yaml` with all recipients
- **Git safety**: Automatically adds `.sops/` to `.gitignore`
- **Zero key management**: Keys derived on-demand in your dev shell

## How It Works

1. Reads your master key from `~/.sops/key.txt`
2. Derives project-specific keys using HKDF with the git repository name as salt
3. Generates multiple keys if suffixes are provided (e.g., `repo+staging`, `repo+prod`)
4. Creates `.sops/keys.txt` with all private keys (for decryption)
5. Creates `.sops.yaml` with all public keys (for encryption recipients)
6. Exports `SOPS_AGE_KEY_FILE` pointing to the local keys file

## Setup

### 1. Generate a Master Key

Create a master key in your home directory:

```bash
mkdir -p ~/.sops
age-keygen -o ~/.sops/key.txt
```

**Important**: Back up this master key securely. It's the only key you need to remember.

### 2. Add to Your Flake

```nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    sops-kdf.url = "github:sapp00/nix-sops-kdf";
  };

  outputs = { self, nixpkgs, sops-kdf }:
  let
    system = "x86_64-linux";
    pkgs = nixpkgs.legacyPackages.${system};
    kdfTool = sops-kdf.packages.${system}.default;
  in {
    devShells.${system}.default = pkgs.mkShell {
      buildInputs = [ pkgs.sops pkgs.age ];

      shellHook = ''
        export EDITOR=vim
        eval "$(${kdfTool}/bin/sops-kdf-hook)"
      '';
    };
  };
}
```

### 3. Enter Your Dev Shell

```bash
nix develop
```

The hook will automatically:
- Derive your project-specific keys
- Create `.sops/keys.txt` and `.sops.yaml`
- Add `.sops/` to `.gitignore`
- Export `SOPS_AGE_KEY_FILE`

## Usage

### Single Key (Default)

For simple projects that don't need environment separation:

```nix
shellHook = ''
  eval "$(${kdfTool}/bin/sops-kdf-hook)"
'';
```

This generates one key derived from your repository name.

### Multiple Keys (Environment-Specific)

For projects with staging, production, or other environments:

```nix
shellHook = ''
  eval "$(${kdfTool}/bin/sops-kdf-hook staging prod)"
'';
```

This generates three keys:
- `github.com/user/repo` (base key)
- `github.com/user/repo+staging`
- `github.com/user/repo+prod`

All three public keys are added to `.sops.yaml`, so you can encrypt secrets for specific environments or all environments.

### Encrypting Secrets

Once configured, use SOPS normally:

```bash
# Create/edit a secret file
sops secrets.yaml

# The file will be encrypted for all recipients in .sops.yaml
```

### Decrypting Secrets

SOPS will automatically use the keys from `.sops/keys.txt` (via `SOPS_AGE_KEY_FILE`):

```bash
# View secrets
sops secrets.yaml

# Decrypt to stdout
sops -d secrets.yaml
```

## Generated Files

### `.sops/keys.txt`

Contains all derived private age keys (newline-separated):

```
# Auto-generated age keys for SOPS
# DO NOT COMMIT THIS FILE

AGE-SECRET-KEY-1...
AGE-SECRET-KEY-1...
```

**Security**: This file has `600` permissions and is auto-ignored by git.

### `.sops.yaml`

SOPS configuration with all public key recipients:

```yaml
creation_rules:
  - path_regex: .*
    age: age1...,age1...,age1...
```

**Tip**: You can customize this file to add path-specific rules.

### `.gitignore`

Automatically updated to include:

```
.sops/
```

This prevents accidentally committing private keys.

## Security Considerations

### Master Key Protection

Your `~/.sops/key.txt` is the root of trust:
- Back it up securely (password manager, encrypted backup)
- Never commit it to git
- Consider encrypting your home directory

### Derived Key Isolation

Each project gets cryptographically isolated keys:
- Same master key + different repos = completely different keys
- Keys are deterministic: same inputs always produce same outputs
- Uses HKDF-SHA256 for secure key derivation

### Per-Environment Keys

Using suffixes creates separate keys for different environments:
- Staging team can only decrypt staging secrets
- Production keys can be restricted to CI/CD
- Each environment is cryptographically isolated

### Key Distribution

To share access with teammates:
1. They need the same master key in their `~/.sops/key.txt`
2. They run `nix develop` to derive the same project keys
3. Or, share specific derived private keys from `.sops/keys.txt` securely

To revoke access:
- Remove their public key from `.sops.yaml`
- Re-encrypt all secrets: `sops updatekeys secrets.yaml`

## How KDF Works

The tool uses HKDF (HMAC-based Key Derivation Function) with SHA-256:

```python
# Extract phase
PRK = HMAC-SHA256(salt='age-kdf-salt', ikm=master_key)

# Expand phase
OKM = HMAC-SHA256(key=PRK, info=repo_id + '\x01')

# Encode as bech32
derived_key = bech32_encode('age-secret-key-', OKM)
```

Where `repo_id` is:
- Base key: `github.com/user/repo`
- Staging key: `github.com/user/repo+staging`
- Prod key: `github.com/user/repo+prod`

## Troubleshooting

### "No .git directory found"

Run the tool inside a git repository with a configured remote origin.

### "No valid key found in ~/.sops/key.txt"

Generate a master key:
```bash
mkdir -p ~/.sops
age-keygen -o ~/.sops/key.txt
```

### "Failed to derive public key"

Ensure `age` is installed and in your PATH:
```bash
nix-shell -p age
```

### Keys not working after regeneration

If you change suffixes or repo URL, new keys are generated. Re-encrypt your secrets:
```bash
sops updatekeys secrets.yaml
```

## Example Project Structure

```
my-project/
├── flake.nix           # Includes sops-kdf in shellHook
├── .git/               # Git repository
├── .gitignore          # Auto-updated with .sops/
├── .sops.yaml          # Auto-generated recipients config
├── .sops/
│   └── keys.txt        # Auto-generated private keys (git-ignored)
└── secrets.yaml        # Your encrypted secrets
```

## Contributing

Issues and pull requests welcome at [github.com/sapp00/nix-sops-kdf](https://github.com/sapp00/nix-sops-kdf).

## License

MIT
