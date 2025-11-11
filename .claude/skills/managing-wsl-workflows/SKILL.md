---
name: managing-wsl-workflows
description: Navigate WSL-specific development patterns, path handling, and environment integration. Use when working across Windows/Linux boundaries, configuring development tools in WSL, or troubleshooting WSL-specific issues.
---

# Managing WSL Workflows

**Purpose**: Efficiently work in Windows Subsystem for Linux (WSL) environment.

## When to Use

- Developing on Windows with Linux tools
- Handling file paths across Windows/Linux
- Configuring development environment in WSL
- Troubleshooting WSL-specific issues
- Optimizing performance for WSL workflows
- Accessing Windows files from Linux or vice versa

## Core Concepts

### File System Access

**Linux → Windows**:
```bash
# Windows drives mounted at /mnt/
cd /mnt/c/Users/peter/Documents
ls /mnt/d/Projects
```

**Windows → Linux**:
```
\\wsl$\Ubuntu\home\peter\project
# Access from Windows Explorer
```

**Best Practice**: Keep project files in Linux filesystem for performance
```bash
# GOOD (fast)
/home/peter/projects/app

# AVOID (slow)
/mnt/c/Users/peter/projects/app
```

### Path Handling

**Convert paths**:
```bash
# Windows path → WSL path
wslpath "C:\Users\peter\file.txt"
# Output: /mnt/c/Users/peter/file.txt

# WSL path → Windows path
wslpath -w /home/peter/file.txt
# Output: \\wsl$\Ubuntu\home\peter\file.txt
```

**In scripts**:
```bash
#!/bin/bash
# Handle both Windows and Linux paths
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    PROJECT_DIR="/home/peter/project"
else
    PROJECT_DIR="/mnt/c/Users/peter/project"
fi
```

## Common Workflows

### Workflow 1: Development Environment Setup

```bash
# Update WSL
sudo apt update && sudo apt upgrade -y

# Install Node.js (use nvm for version management)
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash
source ~/.bashrc
nvm install --lts
nvm use --lts

# Install Python
sudo apt install python3 python3-pip -y

# Install Git (configure once)
sudo apt install git -y
git config --global user.name "Peter Findley"
git config --global user.email "peter@example.com"

# Install Docker (if needed)
# Follow official Docker Desktop for Windows + WSL2 integration
```

### Workflow 2: VS Code Integration

**Open project in VS Code from WSL**:
```bash
cd /home/peter/project
code .  # Opens VS Code with WSL remote extension
```

**VS Code settings** (`.vscode/settings.json`):
```json
{
  "remote.WSL.fileWatcher.polling": true,  // Better file watching
  "terminal.integrated.defaultProfile.linux": "bash",
  "files.eol": "\n"  // Force LF line endings
}
```

### Workflow 3: Running Servers

**Next.js development**:
```bash
cd /home/peter/kids
npm run dev
# Access from Windows: http://localhost:3000
```

**Port forwarding** (automatic in WSL2):
- Servers in WSL accessible from Windows via `localhost`
- No configuration needed for most cases

**Firewall issues**:
```powershell
# Run in PowerShell (Admin) if Windows can't access WSL server
New-NetFirewallRule -DisplayName "WSL" -Direction Inbound -InterfaceAlias "vEthernet (WSL)" -Action Allow
```

## Performance Optimization

### Use Linux Filesystem

**GOOD** (fast):
```bash
# Projects in Linux home
/home/peter/projects/
```

**BAD** (slow):
```bash
# Projects in Windows filesystem
/mnt/c/Users/peter/projects/
```

**Why**: Cross-filesystem operations are slow in WSL

### File Watching

**Problem**: File watchers don't work well across filesystems

**Solution**:
```json
// package.json - Use polling for Windows files
{
  "scripts": {
    "dev": "CHOKIDAR_USEPOLLING=true next dev"
  }
}
```

Or move project to Linux filesystem.

### Memory Management

**Check WSL memory usage**:
```bash
free -h
```

**Configure WSL2 memory** (`.wslconfig` in Windows user folder):
```
[wsl2]
memory=8GB
processors=4
swap=2GB
```

## Common Issues and Fixes

### Issue 1: Line Ending Problems

**Problem**: Git shows all files modified (CRLF vs LF)

**Fix**:
```bash
git config --global core.autocrlf input  # In WSL
# In Windows Git: core.autocrlf = true
```

```.gitattributes
* text=auto eol=lf
*.sh text eol=lf
```

### Issue 2: Permission Issues

**Problem**: Files created in Windows have wrong permissions in WSL

**Fix** (in `/etc/wsl.conf`):
```ini
[automount]
options = "metadata,umask=22,fmask=11"
```

Restart WSL:
```powershell
# In PowerShell
wsl --shutdown
```

### Issue 3: Can't Access Windows Files

**Problem**: `/mnt/c` doesn't exist

**Fix**: Check WSL version and mounting:
```bash
wsl --version  # Ensure WSL2
mount | grep /mnt  # Check if Windows drives mounted
```

### Issue 4: Slow npm install

**Problem**: Installing packages takes forever on Windows filesystem

**Fix**: Move `node_modules` to Linux:
```bash
# In project on /mnt/c
rm -rf node_modules
ln -s /home/peter/.cache/node_modules ./node_modules
npm install  # Now fast
```

## Integration Patterns

### Git Workflow in WSL

```bash
# Clone repos to Linux filesystem for speed
cd ~/projects
git clone https://github.com/pfin/kids.git
cd kids

# Normal git workflow
git status
git add .
git commit -m "feat: new component"
git push origin main
```

### Docker Integration

**Docker Desktop + WSL2**:
- Install Docker Desktop for Windows
- Enable WSL2 backend
- Access Docker from WSL automatically

```bash
# In WSL, use docker normally
docker ps
docker build -t myapp .
docker run -p 3000:3000 myapp
```

### SSH Keys

**Generate in WSL**:
```bash
ssh-keygen -t ed25519 -C "peter@example.com"
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519

# Add public key to GitHub
cat ~/.ssh/id_ed25519.pub
```

**Shared SSH keys** (Windows + WSL):
```bash
# Symlink Windows SSH keys
ln -s /mnt/c/Users/peter/.ssh ~/.ssh
chmod 600 ~/.ssh/id_rsa  # Fix permissions
```

## Checklist

- [ ] WSL2 installed and updated
- [ ] Projects in Linux filesystem (`/home/peter/`)
- [ ] Git configured with correct line endings
- [ ] VS Code WSL extension installed
- [ ] Node.js/Python installed via WSL package managers
- [ ] SSH keys configured
- [ ] `.wslconfig` optimized for memory
- [ ] Docker Desktop WSL2 integration enabled (if using Docker)

## Integration with Other Skills

**Use with**:
- `building-with-nextjs` - Development environment
- `deploying-to-vercel` - Git workflow from WSL
- `midnight-building` - WSL as focused dev environment
- `story-bridge-development` - Kids app development in WSL

## Related Skills

- `building-with-nextjs` - Web development
- `deploying-to-vercel` - Git and deployment
- `integrating-supabase` - Database CLI tools
- `midnight-building` - Focused dev sessions

## Advanced Topics

See resources in this skill folder:
- `advanced-1-networking.md` - Port forwarding and VPN integration
- `advanced-2-performance.md` - Optimizing WSL2 performance
- `advanced-3-backup-restore.md` - WSL distribution backup
