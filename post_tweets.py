"""
Twitter Poster - Synchronous Version (No async/await)
Uses persistent browser profile for maximum reliability.
"""
import time
from playwright.sync_api import sync_playwright
from pathlib import Path
import tweets_data as td


class TwitterPoster:
    """
    Synchronous Twitter poster using persistent browser context.
    No async/await - simple and straightforward.
    """
    
    def __init__(self, profile_dir="./twitter_browser_profile"):
        self.profile_dir = profile_dir
        self.playwright = None
        self.context = None
        self.page = None
    
    def setup_first_time(self):
        """
        Run this ONCE to set up your Twitter login.
        Opens a browser where you log in manually.
        Profile is saved and reused forever.
        """
        print("\n" + "="*70)
        print("FIRST TIME SETUP - TWITTER LOGIN")
        print("="*70)
        print("\nA browser will open. Please:")
        print("1. Log in to Twitter")
        print("2. Complete any 2FA/verification if needed")
        print("3. Wait until you see your Twitter home feed")
        print("4. Come back here and press Enter")
        print("\n" + "="*70 + "\n")
        
        self.playwright = sync_playwright().start()
        
        # Launch persistent context (saves everything automatically)
        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=self.profile_dir,
            headless=False,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage'
            ],
            viewport={'width': 1280, 'height': 800}
        )
        
        # Get the default page
        if len(self.context.pages) > 0:
            self.page = self.context.pages[0]
        else:
            self.page = self.context.new_page()
        
        # Go to Twitter
        self.page.goto("https://twitter.com/login")
        
        # Wait for user to log in
        input("\nPress Enter after you've successfully logged in... ")
        
        print("\n✓ Setup complete! Your browser profile is saved.")
        print(f"  Profile location: {self.profile_dir}")
        print("  You can now use post_tweets() without logging in again.\n")
        
        self.close()
    
    def start(self, headless=False):
        """
        Start browser with saved profile.
        Call this before posting tweets.
        """
        if not Path(self.profile_dir).exists():
            raise FileNotFoundError(
                f"Browser profile not found: {self.profile_dir}\n"
                "Run setup_first_time() first to create your profile."
            )
        
        self.playwright = sync_playwright().start()
        
        # Launch with saved profile
        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=self.profile_dir,
            headless=headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage'
            ],
            viewport={'width': 1280, 'height': 800}
        )
        
        # Get or create page
        if len(self.context.pages) > 0:
            self.page = self.context.pages[0]
        else:
            self.page = self.context.new_page()
        
        # Verify we're logged in
        self.page.goto("https://twitter.com/home", wait_until="domcontentloaded")
        time.sleep(2)
        
        if "login" in self.page.url:
            self.close()
            raise Exception(
                "Not logged in. Your session may have expired.\n"
                "Run setup_first_time() again to log in."
            )
        
        print("✓ Started browser session - ready to post tweets")
    
    def post_tweet(self, tweet_text, wait_after=3):
        """
        Post a single tweet.
        
        Args:
            tweet_text: The text content of the tweet
            wait_after: Seconds to wait after posting (default 3)
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Make sure we're on home page
            if "home" not in self.page.url:
                self.page.goto("https://twitter.com/home", wait_until="domcontentloaded")
                time.sleep(2)
            
            # Find the tweet compose box
            tweet_box = None
            
            # Try multiple selectors
            selectors = [
                'div[data-testid="tweetTextarea_0"]',
                'div[role="textbox"][data-testid="tweetTextarea_0"]',
                'div[aria-label="Post text"]'
            ]
            
            for selector in selectors:
                try:
                    tweet_box = self.page.wait_for_selector(selector, timeout=5000)
                    if tweet_box:
                        break
                except:
                    continue
            
            if not tweet_box:
                self.page.screenshot(path="debug_screenshot.png")
                raise Exception("Could not find tweet box. Screenshot saved.")
            
            # Click and type the tweet
            tweet_box.click()
            time.sleep(0.5)
            tweet_box.type(tweet_text, delay=50)  # Type with slight delay
            time.sleep(1)
            
            # Find and click Post button
            post_button = None
            post_selectors = [
                'div[data-testid="tweetButtonInline"]',
                'button[data-testid="tweetButtonInline"]',
                'div[data-testid="tweetButton"]',
            ]
            
            for selector in post_selectors:
                try:
                    post_button = self.page.wait_for_selector(selector, timeout=3000)
                    if post_button:
                        break
                except:
                    continue
            
            if not post_button:
                raise Exception("Could not find Post button")
            
            # Click post
            post_button.click()
            time.sleep(wait_after)
            
            print(f"✓ Posted: {tweet_text[:60]}{'...' if len(tweet_text) > 60 else ''}")
            return True
            
        except Exception as e:
            print(f"✗ Failed: {e}")
            print(f"  Tweet: {tweet_text[:60]}...")
            return False
    
    def post_tweets(self, tweets, delay_between=8):
        """
        Post multiple tweets from a list.
        
        Args:
            tweets: List of tweet text strings
            delay_between: Seconds to wait between tweets (minimum 5 recommended)
        
        Returns:
            dict: Results with 'successful' and 'failed' counts
        """
        if delay_between < 5:
            print("⚠ Warning: Delay less than 5 seconds may trigger rate limits")
        
        print(f"\n{'='*70}")
        print(f"Posting {len(tweets)} tweets")
        print(f"Delay between tweets: {delay_between} seconds")
        print(f"{'='*70}\n")
        
        successful = 0
        failed = 0
        
        for i, tweet in enumerate(tweets, 1):
            print(f"\n[{i}/{len(tweets)}] Posting tweet...")
            
            if self.post_tweet(tweet, wait_after=3):
                successful += 1
            else:
                failed += 1
            
            # Wait between tweets (except after last one)
            if i < len(tweets):
                print(f"⏳ Waiting {delay_between} seconds...")
                time.sleep(delay_between)
        
        # Print summary
        print(f"\n{'='*70}")
        print(f"COMPLETE!")
        print(f"{'='*70}")
        print(f"✓ Successful: {successful}")
        print(f"✗ Failed: {failed}")
        print(f"Total: {len(tweets)}")
        print(f"{'='*70}\n")
        
        return {'successful': successful, 'failed': failed, 'total': len(tweets)}
    
    def close(self):
        """Close browser and clean up."""
        if self.context:
            self.context.close()
        if self.playwright:
            self.playwright.stop()


# Simple example usage
def main():
    # Your list of tweets
    my_tweets = td.tweets_0 + td.tweets_1 + td.tweets_2 + td.tweets_3 + td.tweets_4
    
    poster = TwitterPoster()
    
    # STEP 1: First time only - set up your login
    # Uncomment this line and run once:
    # poster.setup_first_time()
    
    # STEP 2: After setup, post your tweets
    # Comment out setup_first_time() above, then use this:
    try:
        poster.start(headless=False)  # Set headless=True to hide browser
        poster.post_tweets(my_tweets, delay_between=10)
    finally:
        poster.close()


if __name__ == "__main__":
    main()
