"""
Twitter Auto-Reposter — @grok edition
Scans the Notifications tab, reposts ONLY tweets that start with "@grok ",
skips everything else (including other tweets, likes, follows, etc.).
Halts the moment it encounters a tweet that has already been reposted.
Uses persistent browser profile — no session.json needed.
Updated for X.com 2026 behavior (selectors stable, longer waits).
"""

import time
from playwright.sync_api import sync_playwright
from pathlib import Path


class NotificationReposter:

    KEYWORD = "@grok"

    def __init__(self, profile_dir: str = "./twitter_browser_profile"):
        self.profile_dir = profile_dir
        self.playwright  = None
        self.context     = None
        self.page        = None

    # ── First-time login ───────────────────────────────────────────────────

    def setup_first_time(self):
        print("\n" + "=" * 70)
        print("FIRST TIME SETUP — TWITTER LOGIN")
        print("=" * 70)
        print("\nA browser will open. Please log in, then press Enter here.")
        print("=" * 70 + "\n")

        pw  = sync_playwright().start()
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=self.profile_dir,
            headless=False,
            args=["--disable-blink-features=AutomationControlled",
                  "--disable-dev-shm-usage"],
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://twitter.com/login")
        input("\nPress Enter after you have successfully logged in… ")
        ctx.close()
        pw.stop()
        print(f"\n✓ Setup complete! Profile saved to: {self.profile_dir}\n")

    # ── Browser lifecycle ──────────────────────────────────────────────────

    def _start(self, headless: bool = False):
        if not Path(self.profile_dir).exists():
            raise FileNotFoundError(
                f"Profile not found: {self.profile_dir}\n"
                "Run setup_first_time() first."
            )
        self.playwright = sync_playwright().start()
        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=self.profile_dir,
            headless=headless,
            args=["--disable-blink-features=AutomationControlled",
                  "--disable-dev-shm-usage"],
            viewport={"width": 1280, "height": 800},
        )
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.goto("https://twitter.com/with_replies", wait_until="domcontentloaded")
        time.sleep(4)  # Increased for 2026 load times

        if "login" in self.page.url:
            raise RuntimeError("Not logged in. Run setup_first_time() again.")

        print("✓ Loaded notifications tab\n")

    def _stop(self):
        if self.context:
            self.context.close()
        if self.playwright:
            self.playwright.stop()

    # ── Notification helpers ───────────────────────────────────────────────

    def _is_repostable(self, article) -> bool:
        """Has retweet button → it's a tweet notification we can potentially repost."""
        try:
            return article.query_selector('[data-testid="retweet"]') is not None
        except Exception:
            return False

    def _get_tweet_text(self, article) -> str:
        try:
            el = article.query_selector('[data-testid="tweetText"]')
            if el:
                return el.inner_text().strip()
        except Exception:
            pass
        return ""

    def _starts_with_grok(self, article) -> bool:
        text = self._get_tweet_text(article)
        return text.lower().startswith(self.KEYWORD.lower())

    def _is_already_retweeted(self, article) -> bool:
        try:
            btn = article.query_selector('[data-testid="retweet"]')
            if not btn:
                return False
            label = btn.get_attribute("aria-label") or ""
            if "undo repost" in label.lower() or "undo retweet" in label.lower():
                return True
            # Fallback: check color/style (green when active)
            if "rgb(0, 186, 124)" in btn.inner_html():
                return True
            return False
        except Exception:
            return False

    # ── Repost action ──────────────────────────────────────────────────────

    def _retweet(self, article, idx: int) -> bool:
        try:
            btn = article.query_selector('[data-testid="retweet"]')
            btn.click()
            time.sleep(1.2)

            confirm = self.page.wait_for_selector(
                '[data-testid="retweetConfirm"]', timeout=5000
            )
            confirm.click()
            time.sleep(1.8)  # Wait for action to complete

            print(f"  [{idx}] ✓ Reposted")
            return True

        except Exception as exc:
            print(f"  [{idx}] ✗ Failed to repost: {exc}")
            if hasattr(self, 'page') and self.page:
                try:
                    self.page.screenshot(path=f"repost-error-{idx}.png")
                    print(f"     → Screenshot saved: repost-error-{idx}.png")
                except:
                    pass
            try:
                self.page.keyboard.press("Escape")
            except:
                pass
            return False

    # ── Main loop ──────────────────────────────────────────────────────────

    def run(
        self,
        headless: bool = False,
        delay_between: float = 2.5,
        max_scrolls: int = 30,
    ):
        """
        Walk down Notifications and repost ONLY tweets starting with "@grok ".
        Halts immediately when an already-reposted @grok tweet is found.
        """
        self._start(headless=headless)

        reposted  = 0
        skipped   = 0
        halted    = False
        tweet_idx = 0
        seen_ids  = set()

        print(f"{'=' * 70}")
        print(f"Starting notification scan — reposting ONLY tweets starting with '{self.KEYWORD} ' …")
        print(f"{'=' * 70}\n")

        for scroll_round in range(max_scrolls):

            articles  = self.page.query_selector_all('article[data-testid="tweet"]')
            new_tweets_found = 0

            for article in articles:
                try:
                    snippet = article.inner_text()[:120]
                except Exception:
                    continue

                if snippet in seen_ids:
                    continue
                seen_ids.add(snippet)

                if not self._is_repostable(article):
                    continue  # not a tweet notification

                text_preview = self._get_tweet_text(article)[:50]
                if not self._starts_with_grok(article):
                    print(f"[{tweet_idx+1}] Skipped (not starting with {self.KEYWORD}): {text_preview}…")
                    skipped += 1
                    continue

                # It's a @grok tweet → count it
                tweet_idx += 1
                new_tweets_found += 1
                print(f"[{tweet_idx}] @grok tweet found | {text_preview}…")

                if self._is_already_retweeted(article):
                    print(f"[{tweet_idx}] Already reposted — halting.\n")
                    halted = True
                    break

                if self._retweet(article, tweet_idx):
                    reposted += 1
                else:
                    skipped += 1

                time.sleep(delay_between)

            if halted:
                break

            if new_tweets_found == 0:
                print("No new @grok tweets found after scroll — feed exhausted.")
                break

            print(f"\n  Scrolling for more... (round {scroll_round + 1})\n")
            self.page.evaluate("window.scrollBy(0, window.innerHeight * 3)")
            time.sleep(3.0)  # Slightly longer for lazy loading

        self._stop()

        print(f"{'=' * 70}")
        print("DONE")
        print(f"{'=' * 70}")
        print(f"  Reposted : {reposted}")
        print(f"  Skipped  : {skipped}  (non-@grok or errors)")
        print(f"  Halted   : {'Yes — hit already-reposted @grok tweet' if halted else 'No (reached end of feed)'}")
        print(f"{'=' * 70}\n")

        return {"reposted": reposted, "skipped": skipped, "halted": halted}


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    reposter = NotificationReposter(profile_dir="./twitter_browser_profile")

    # First time only — uncomment and run once:
    # reposter.setup_first_time()

    reposter.run(
        headless=False,           # Set to True once stable
        delay_between=2.5,
        max_scrolls=40,           # Increased a bit — @grok tweets may be sparse
    )


if __name__ == "__main__":
    main()
