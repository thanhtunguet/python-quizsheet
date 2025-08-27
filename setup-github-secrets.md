# GitHub Secrets Setup Guide

This guide helps you set up the required secrets for the GitHub Actions workflows to work properly.

## Required Secrets

### DockerHub Integration

1. **DOCKERHUB_USERNAME**
   - Your DockerHub username
   - Example: `johnsmith`

2. **DOCKERHUB_TOKEN** 
   - Your DockerHub access token (NOT your password)
   - How to create:
     1. Log in to [DockerHub](https://hub.docker.com/)
     2. Go to Account Settings → Security
     3. Click "New Access Token"
     4. Give it a descriptive name (e.g., "GitHub Actions")
     5. Copy the generated token

## How to Add Secrets to GitHub

1. **Navigate to your repository on GitHub**

2. **Go to Settings**
   - Click on the "Settings" tab in your repository

3. **Access Secrets and Variables**
   - In the left sidebar, click "Secrets and variables"
   - Click "Actions"

4. **Add Repository Secrets**
   - Click "New repository secret"
   - Add each secret with the exact name shown above
   - Paste the corresponding value
   - Click "Add secret"

## Verification

After adding the secrets:

1. **Check the workflow file**
   - Make sure `.github/workflows/docker-build-push.yml` exists
   - Verify it references the correct secret names

2. **Test the workflow**
   - Push a commit to the `main` branch
   - Go to the "Actions" tab in your repository
   - Watch the workflow run and check for any errors

3. **Verify Docker image**
   - After successful workflow run, check your DockerHub repository
   - The image should be available at: `your-username/quiz-processor`

## Troubleshooting

### Common Issues

- **"Secret not found"**: Double-check the secret name matches exactly
- **"Authentication failed"**: Verify your DockerHub token is correct and has push permissions
- **"Repository not found"**: Make sure your DockerHub username is correct in the workflow

### Getting Help

If you encounter issues:
1. Check the GitHub Actions logs for detailed error messages
2. Verify your DockerHub credentials manually
3. Ensure your DockerHub repository exists (it will be created automatically on first push)

## Security Best Practices

- ✅ Use access tokens, not passwords
- ✅ Give tokens only the minimum required permissions
- ✅ Regularly rotate your access tokens
- ✅ Monitor your DockerHub for unexpected activity
- ❌ Never commit secrets to your repository
- ❌ Don't share access tokens in issues or pull requests
