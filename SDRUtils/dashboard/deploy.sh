#!/bin/bash

# SDR Monitor Dashboard Deployment Script

echo "🚀 Deploying SDR Monitor Dashboard to Vercel..."

# Check if we're in the right directory
if [ ! -f "package.json" ]; then
    echo "❌ Error: Must run from sdr-monitor/dashboard directory"
    exit 1
fi

# Check if vercel CLI is installed
if ! command -v vercel &> /dev/null; then
    echo "❌ Error: Vercel CLI not found. Install with: npm i -g vercel"
    exit 1
fi

# Check if project is already linked
if [ ! -d ".vercel" ] || [ ! -f ".vercel/project.json" ]; then
    echo "⚠️  Project not linked yet. Linking to sp-sdr..."
    echo "📝 When prompted:"
    echo "   - Set up and deploy: Y"
    echo "   - Which scope: Choose your account"
    echo "   - Link to existing project: Y"
    echo "   - What's the name of your existing project: sp-sdr"
    echo ""
fi

# Production deployment
if [ "$1" == "--prod" ]; then
    echo "📦 Deploying to production..."
    vercel --prod --yes
else
    echo "📦 Deploying to preview..."
    vercel --yes
    echo ""
    echo "💡 Tip: Use './deploy.sh --prod' for production deployment"
fi

echo "✅ Deployment complete!"