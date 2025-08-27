#!/usr/bin/env python3
"""
Setup verification script for the Quiz Sheet Processing API.
Checks that all required files and configurations are in place.
"""

import os
import sys
import yaml
from pathlib import Path

def check_file_exists(file_path, description):
    """Check if a file exists and report status."""
    if os.path.exists(file_path):
        print(f"✅ {description}: {file_path}")
        return True
    else:
        print(f"❌ {description}: {file_path} (MISSING)")
        return False

def check_yaml_valid(file_path, description):
    """Check if a YAML file exists and is valid."""
    if not check_file_exists(file_path, description):
        return False
    
    try:
        with open(file_path, 'r') as f:
            yaml.safe_load(f)
        print(f"  └─ Valid YAML syntax")
        return True
    except yaml.YAMLError as e:
        print(f"  └─ ❌ YAML Error: {e}")
        return False

def main():
    """Main verification function."""
    print("🔍 Verifying Quiz Sheet API Setup...\n")
    
    all_good = True
    
    # Core application files
    print("📦 Core Application Files:")
    all_good &= check_file_exists("main.py", "Main application")
    all_good &= check_file_exists("system_prompt.hbs", "System prompt template")
    all_good &= check_file_exists("requirements.txt", "Python dependencies")
    all_good &= check_file_exists("healthcheck.py", "Health check script")
    print()
    
    # Docker files
    print("🐳 Docker Configuration:")
    all_good &= check_file_exists("Dockerfile", "Docker image definition")
    all_good &= check_yaml_valid("docker-compose.yml", "Docker Compose configuration")
    all_good &= check_file_exists(".dockerignore", "Docker ignore file")
    print()
    
    # GitHub Actions workflows
    print("🚀 GitHub Actions Workflows:")
    all_good &= check_yaml_valid(".github/workflows/docker-build-push.yml", "Docker build workflow")
    all_good &= check_yaml_valid(".github/workflows/test.yml", "Test workflow")
    all_good &= check_yaml_valid(".github/dependabot.yml", "Dependabot configuration")
    print()
    
    # Documentation
    print("📚 Documentation:")
    all_good &= check_file_exists("README.md", "Main documentation")
    all_good &= check_file_exists("setup-github-secrets.md", "GitHub secrets setup guide")
    print()
    
    # Git configuration
    print("📝 Git Configuration:")
    all_good &= check_file_exists(".gitignore", "Git ignore file")
    print()
    
    # Environment files
    print("🔧 Environment Configuration:")
    if check_file_exists(".env", "Environment variables"):
        print("  └─ Remember to update with your actual API keys")
    else:
        print("  └─ Create .env file with your API keys before running")
    print()
    
    # Check Python imports
    print("🐍 Python Import Test:")
    try:
        import main
        print("✅ Main application imports successfully")
        
        # Test system prompt loading
        prompt = main._load_system_prompt()
        if len(prompt) > 0:
            print("✅ System prompt loads successfully")
        else:
            print("❌ System prompt is empty")
            all_good = False
            
    except Exception as e:
        print(f"❌ Import error: {e}")
        all_good = False
    print()
    
    # Final summary
    if all_good:
        print("🎉 All checks passed! Your setup is ready.")
        print("\n📋 Next Steps:")
        print("1. Update .env with your actual API keys")
        print("2. Set up GitHub secrets for DockerHub (see setup-github-secrets.md)")
        print("3. Update README badges with your GitHub/DockerHub usernames")
        print("4. Push to GitHub to trigger the CI/CD pipeline")
        print("5. Test the application: uvicorn main:app --reload --port 8000")
        return 0
    else:
        print("❌ Some checks failed. Please fix the issues above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
