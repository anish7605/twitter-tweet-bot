"""
Grok Reply Reposter
Goes to your Replies tab, scans each tweet, and reposts only tweets
that begin with the keyword "@grok". Halts the moment it finds an
already-reposted @grok tweet. Non-grok tweets and other notifications
are silently skipped.
Uses persistent browser profile — no session.json needed.
"""

import time
from playwright.sync_api import sync_playwright
from pathlib import Path


class GrokReplyReposter:

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

        # Navigate to your own Replies tab
        # First grab the logged-in username from the page
        self.page.goto("https://twitter.com/home", wait_until="domcontentloaded")
        time.sleep(3)

        if "login" in self.page.url:
            raise RuntimeError("Not logged in. Run setup_first_time() again.")

        username = self._get_username()
        replies_url = f"https://twitter.com/{username}/with_replies"
        print(f"✓ Logged in as @{username}")
        print(f"  Navigating to replies tab: {replies_url}\n")

        self.page.goto(replies_url, wait_until="domcontentloaded")
        time.sleep(3)

    def _get_username(self) -> str:
        """Extract the logged-in username from the sidebar."""
        try:
            # The profile link in the sidebar contains the username
            handle = self.page.query_selector('[data-testid="SideNav_AccountSwitcher_Button"]')
            if handle:
                text = handle.inner_text()
                for line in text.split("\n"):
                    line = line.strip()
                    if line.startswith("@"):
                        return line[1:]
            # Fallback: try the profile link
            profile_link = self.page.query_selector('a[data-testid="AppTabBar_Profile_Link"]')
            if profile_link:
                href = profile_link.get_attribute("href") or ""
                if href.startswith("/"):
                    return href.strip("/")
        except Exception:
            pass
        raise RuntimeError(
            "Could not detect your username automatically.\n"
            "Set it manually: reposter.run(username='yourhandle')"
        )

    def _stop(self):
        if self.context:
            self.context.close()
        if self.playwright:
            self.playwright.stop()

    # ── Tweet content helpers ──────────────────────────────────────────────

    def _get_tweet_text(self, article) -> str:
        """Extract the visible tweet text from an article element."""
        try:
            text_el = article.query_selector('[data-testid="tweetText"]')
            if text_el:
                return text_el.inner_text().strip()
        except Exception:
            pass
        return ""

    def _starts_with_grok(self, article) -> bool:
        """Returns True if the tweet text starts with @grok (case-insensitive)."""
        text = self._get_tweet_text(article)
        return text.lower().startswith(self.KEYWORD.lower())

    def _has_retweet_button(self, article) -> bool:
        """Returns True if this article has a retweet button (i.e. is a tweet, not a header)."""
        try:
            btn = article.query_selector('[data-testid="retweet"]')
            return btn is not None
        except Exception:
            return False

    def _is_already_retweeted(self, article) -> bool:
        """Returns True if the retweet button is already in active (green) state."""
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

            text_preview = self._get_tweet_text(article)[:60]
            print(f"  [{idx}] ✓ Reposted: {text_preview}…")
            return True

        except Exception as exc:
            print(f"  [{idx}] ✗ Failed to repost: {exc}")
            try:
                self.page.keyboard.press("Escape")
            except Exception:
                pass
            return False

    # ── Main loop ──────────────────────────────────────────────────────────

    def run(
        self,
        username: str = None,
        headless: bool = False,
        delay_between: float = 2.0,
        max_scrolls: int = 30,
    ):
        """
        Scan the Replies tab and repost every @grok tweet not yet reposted.
        Halts immediately when a @grok tweet that is already reposted is found.
        Non-@grok tweets are silently skipped.

        Args:
            username:       Your Twitter handle (without @). Auto-detected if None.
            headless:       Hide the browser window.
            delay_between:  Seconds to wait between each repost.
            max_scrolls:    Safety cap on scroll rounds.
        """
        # If username is provided manually, override auto-detect
        if username:
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
            replies_url = f"https://twitter.com/{username}/with_replies"
            print(f"  Navigating to replies tab: {replies_url}\n")
            self.page.goto(replies_url, wait_until="domcontentloaded")
            time.sleep(3)
        else:
            self._start(headless=headless)

        reposted  = 0
        skipped   = 0
        halted    = False
        tweet_idx = 0
        seen_ids  = set()

        print(f"{'=' * 70}")
        print(f"Scanning replies tab for tweets starting with '{self.KEYWORD}'…")
        print(f"{'=' * 70}\n")

        for scroll_round in range(max_scrolls):

            articles  = self.page.query_selector_all('article[data-testid="tweet"]')
            new_found = 0

            for article in articles:
                try:
                    snippet = article.inner_text()[:120]
                except Exception:
                    continue

                if snippet in seen_ids:
                    continue
                seen_ids.add(snippet)
                new_found += 1

                # ── Must have a retweet button (skips headers, ads, etc.)
                if not self._has_retweet_button(article):
                    continue

                # ── Must start with @grok — everything else is silently skipped
                if not self._starts_with_grok(article):
                    continue

                tweet_idx += 1
                text_preview = self._get_tweet_text(article)[:60]
                print(f"[{tweet_idx}] @grok tweet found: {text_preview}…")

                # ── Already reposted → halt immediately
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

            if halted:
                break

            if new_found == 0:
                print("No new tweets found after scroll — feed exhausted.")
                break

            print(f"\n  Scrolling for more… (round {scroll_round + 1})\n")
            self.page.evaluate("window.scrollBy(0, window.innerHeight * 3)")
            time.sleep(2.5)

        self._stop()

        print(f"{'=' * 70}")
        print("DONE")
        print(f"{'=' * 70}")
        print(f"  Keyword   : {self.KEYWORD}")
        print(f"  Reposted  : {reposted}")
        print(f"  Skipped   : {skipped}")
        print(f"  Halted    : {'Yes — hit an already-reposted @grok tweet' if halted else 'No (reached end of feed)'}")
        print(f"{'=' * 70}\n")

        return {"reposted": reposted, "skipped": skipped, "halted": halted}


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    reposter = GrokReplyReposter(profile_dir="./twitter_browser_profile")

    # First time only — uncomment and run once:
    # reposter.setup_first_time()

    reposter.run(
        # username="grokfc755",  # optional — auto-detected from profile
        headless=False,
        delay_between=2.5,
        max_scrolls=30,
    )


if __name__ == "__main__":
    main()
