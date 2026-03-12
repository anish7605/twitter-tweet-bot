cat > /mnt/user-data/outputs/run_bot.sh << 'EOF'
#!/bin/bash

echo "========================================"
echo " Twitter Bot Runner"
echo "========================================"

echo ""
echo "[1/2] Running tweet poster..."
python3 post_tweets.py

if [ $? -ne 0 ]; then
    echo "post_tweets.py failed — aborting."
    exit 1
fi

echo ""
echo "[2/2] Running auto-reposter..."
python3 auto-reposter.py

echo ""
echo "Done."
EOF
chmod +x /mnt/user-data/outputs/run_bot.sh
