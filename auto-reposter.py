"""
Twitter Auto-Reposter
Scans the Notifications tab, retweets everything not yet retweeted,
and halts the moment it encounters a tweet that has already been retweeted.
Likes, follows, and other non-tweet notifications are silently skipped.
Uses persistent browser profile — no session.json needed.
"""

import time
from playwright.sync_api import sync_playwright
from pathlib import Path


class NotificationReposter:

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
        self.page.goto("https://twitter.com/notifications", wait_until="domcontentloaded")
        time.sleep(3)

        if "login" in self.page.url:
            raise RuntimeError("Not logged in. Run setup_first_time() again.")

        print("✓ Loaded notifications tab\n")

    def _stop(self):
        if self.context:
            self.context.close()
        if self.playwright:
            self.playwright.stop()

    # ── Notification type check ────────────────────────────────────────────

    def _is_repostable(self, article) -> bool:
        """
        Returns True only if this notification card contains an actual tweet
        that can be reposted (i.e. has a retweet button).
        Likes, follows, mentions-without-quote, and system notifications
        either have no article at all or no retweet button — all return False.
        """
        try:
            btn = article.query_selector('[data-testid="retweet"]')
            return btn is not None
        except Exception:
            return False

    # ── Retweet state check ────────────────────────────────────────────────

    def _is_already_retweeted(self, article) -> bool:
        """
        Returns True if the retweet button is already in its active state.
        Only call this AFTER confirming _is_repostable() == True.
        """
        try:
            btn = article.query_selector('[data-testid="retweet"]')
            if not btn:
                return False

            label = btn.get_attribute("aria-label") or ""
            if "undo repost" in label.lower():
                return True

            inner = btn.inner_html()
            if "rgb(0, 186, 124)" in inner or "color-retweet" in inner:
                return True

            return False
        except Exception:
            return False

    # ── Repost action ──────────────────────────────────────────────────────

    def _retweet(self, article, idx: int) -> bool:
        try:
            btn = article.query_selector('[data-testid="retweet"]')
            btn.click()
            time.sleep(1)

            confirm = self.page.wait_for_selector(
                '[data-testid="retweetConfirm"]', timeout=4_000
            )
            confirm.click()
            time.sleep(1.5)

            print(f"  [{idx}] ✓ Reposted")
            return True

        except Exception as exc:
            print(f"  [{idx}] ✗ Failed: {exc}")
            try:
                self.page.keyboard.press("Escape")
            except Exception:
                pass
            return False

    # ── Main loop ──────────────────────────────────────────────────────────

    def run(
        self,
        headless: bool = False,
        delay_between: float = 2.0,
        max_scrolls: int = 30,
    ):
        """
        Walk down Notifications and repost every unretweeted tweet.
        
        - Likes, follows, and other non-tweet notifications are silently skipped.
        - Halts immediately when a tweet that was already reposted is found.
        """
        self._start(headless=headless)

        reposted  = 0
        skipped   = 0
        halted    = False
        tweet_idx = 0
        seen_ids  = set()

        print(f"{'=' * 70}")
        print("Starting notification scan...")
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

                # ── Not a repostable tweet (like, follow, etc.) → skip silently
                if not self._is_repostable(article):
                    continue

                # Only repostable tweets count
                new_tweets_found += 1
                tweet_idx += 1
                print(f"[{tweet_idx}] Checking tweet...")

                # ── Already reposted → halt immediately, exit everything
                if self._is_already_retweeted(article):
                    print(f"[{tweet_idx}] Already reposted — halting.\n")
                    halted = True
                    break

                # ── Not yet reposted → repost it
                if self._retweet(article, tweet_idx):
                    reposted += 1
                else:
                    skipped += 1

                time.sleep(delay_between)

            # Exit scroll loop immediately on halt
            if halted:
                break

            if new_tweets_found == 0:
                print("No new repostable tweets found after scroll — feed exhausted.")
                break

            print(f"\n  Scrolling for more... (round {scroll_round + 1})\n")
            self.page.evaluate("window.scrollBy(0, window.innerHeight * 3)")
            time.sleep(2.5)

        self._stop()

        print(f"{'=' * 70}")
        print("DONE")
        print(f"{'=' * 70}")
        print(f"  Reposted : {reposted}")
        print(f"  Skipped  : {skipped}")
        print(f"  Halted   : {'Yes — hit an already-reposted tweet' if halted else 'No (reached end of feed)'}")
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
        headless=False,
        delay_between=2.5,
        max_scrolls=30,
    )


if __name__ == "__main__":
    main()
