"""
Grok Commenter
Goes to your Replies tab, finds every @grok tweet, and if it has
zero replies/comments — posts a comment "@grok" on it.
Halts the moment it finds an already-commented @grok tweet.
Uses persistent browser profile — no session.json needed.
"""

import time
from playwright.sync_api import sync_playwright
from pathlib import Path


class GrokCommenter:

    KEYWORD = "@grok"
    COMMENT = "@grok"

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

    def _launch(self, headless: bool):
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

    def _stop(self):
        if self.context:
            self.context.close()
        if self.playwright:
            self.playwright.stop()

    # ── Username detection ─────────────────────────────────────────────────

    def _get_username(self) -> str:
        try:
            handle = self.page.query_selector('[data-testid="SideNav_AccountSwitcher_Button"]')
            if handle:
                for line in handle.inner_text().split("\n"):
                    line = line.strip()
                    if line.startswith("@"):
                        return line[1:]
            profile_link = self.page.query_selector('a[data-testid="AppTabBar_Profile_Link"]')
            if profile_link:
                href = profile_link.get_attribute("href") or ""
                if href.startswith("/"):
                    return href.strip("/")
        except Exception:
            pass
        raise RuntimeError(
            "Could not detect username. Pass username='yourhandle' to run()."
        )

    # ── Per-article helpers ────────────────────────────────────────────────

    def _get_tweet_text(self, article) -> str:
        try:
            el = article.query_selector('[data-testid="tweetText"]')
            if el:
                return el.inner_text().strip()
        except Exception:
            pass
        return ""

    def _starts_with_grok(self, article) -> bool:
        return self._get_tweet_text(article).lower().startswith(self.KEYWORD.lower())

    def _has_retweet_button(self, article) -> bool:
        try:
            return article.query_selector('[data-testid="retweet"]') is not None
        except Exception:
            return False

    def _get_reply_count(self, article) -> int:
        """
        Read the reply count from the reply button aria-label.
        e.g. aria-label="3 Replies" → 3
             aria-label="Reply"     → 0  (no replies yet)
        """
        try:
            btn = article.query_selector('[data-testid="reply"]')
            if not btn:
                return 0
            label = btn.get_attribute("aria-label") or ""
            # "0 Replies", "1 Reply", "12 Replies", or just "Reply"
            parts = label.strip().split()
            if parts and parts[0].isdigit():
                return int(parts[0])
            return 0
        except Exception:
            return 0

    def _already_commented_by_me(self, tweet_url: str) -> bool:
        """
        Open the tweet detail page and check if we already left a comment.
        We look for a reply article that:
          - contains our own username handle, AND
          - whose text starts with @grok
        """
        try:
            detail_page = self.context.new_page()
            detail_page.goto(tweet_url, wait_until="domcontentloaded")
            time.sleep(2.5)

            replies = detail_page.query_selector_all('article[data-testid="tweet"]')
            # skip the first article — that's the original tweet itself
            for reply_article in replies[1:]:
                text = ""
                try:
                    el = reply_article.query_selector('[data-testid="tweetText"]')
                    if el:
                        text = el.inner_text().strip()
                except Exception:
                    pass
                if text.lower().startswith(self.COMMENT.lower()):
                    detail_page.close()
                    return True

            detail_page.close()
            return False
        except Exception:
            try:
                detail_page.close()
            except Exception:
                pass
            return False

    def _get_tweet_url(self, article) -> str | None:
        """Get the permalink URL for this tweet via the timestamp link."""
        try:
            time_el = article.query_selector("time")
            if time_el:
                anchor = time_el.evaluate_handle("el => el.closest('a')")
                if anchor:
                    href = anchor.get_attribute("href")
                    if href:
                        return "https://twitter.com" + href
        except Exception:
            pass
        return None

    # ── Comment action ─────────────────────────────────────────────────────

    def _post_comment(self, tweet_url: str, idx: int) -> bool:
        """
        Open the tweet, click Reply, type COMMENT, submit.
        Returns True on success.
        """
        try:
            detail_page = self.context.new_page()
            detail_page.goto(tweet_url, wait_until="domcontentloaded")
            time.sleep(2.5)

            # Click the reply button on the first (original) tweet article
            articles = detail_page.query_selector_all('article[data-testid="tweet"]')
            if not articles:
                detail_page.close()
                return False

            reply_btn = articles[0].query_selector('[data-testid="reply"]')
            if not reply_btn:
                detail_page.close()
                return False

            reply_btn.click()
            time.sleep(1.5)

            # Type into the reply composer
            composer = detail_page.wait_for_selector(
                '[data-testid="tweetTextarea_0"]', timeout=5_000
            )
            composer.click()
            time.sleep(0.5)
            composer.type(self.COMMENT, delay=50)
            time.sleep(0.8)

            # Submit
            submit_btn = detail_page.wait_for_selector(
                '[data-testid="tweetButton"]', timeout=4_000
            )
            submit_btn.click()
            time.sleep(2)

            detail_page.close()
            print(f"  [{idx}] ✓ Commented '{self.COMMENT}' on: {tweet_url}")
            return True

        except Exception as exc:
            print(f"  [{idx}] ✗ Failed to comment: {exc}")
            try:
                detail_page.close()
            except Exception:
                pass
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
        delay_between: float = 3.0,
        max_scrolls: int = 30,
    ):
        """
        Scan the Replies tab. For every @grok tweet:
          - If reply count == 0  → post a comment "@grok"
          - If reply count  > 0  AND we already commented → halt
          - If reply count  > 0  AND we haven't commented → post comment anyway
        Non-@grok tweets are silently skipped.

        Args:
            username:       Your Twitter handle (without @). Auto-detected if None.
            headless:       Hide the browser window.
            delay_between:  Seconds to wait between actions.
            max_scrolls:    Safety cap on scroll rounds.
        """
        self._launch(headless=headless)

        # Navigate home first for username detection
        self.page.goto("https://twitter.com/home", wait_until="domcontentloaded")
        time.sleep(3)

        if "login" in self.page.url:
            raise RuntimeError("Not logged in. Run setup_first_time() first.")

        if not username:
            username = self._get_username()

        replies_url = f"https://twitter.com/{username}/with_replies"
        print(f"✓ Logged in as @{username}")
        print(f"  Navigating to: {replies_url}\n")
        self.page.goto(replies_url, wait_until="domcontentloaded")
        time.sleep(3)

        commented = 0
        skipped   = 0
        halted    = False
        tweet_idx = 0
        seen_ids  = set()

        print("=" * 70)
        print(f"Scanning replies tab — commenting '{self.COMMENT}' on zero-reply @grok tweets…")
        print("=" * 70 + "\n")

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

                # Must be an actual tweet (has retweet button)
                if not self._has_retweet_button(article):
                    continue

                # Must start with @grok
                if not self._starts_with_grok(article):
                    continue

                tweet_idx += 1
                text_preview = self._get_tweet_text(article)[:60]
                reply_count  = self._get_reply_count(article)
                tweet_url    = self._get_tweet_url(article)

                print(f"[{tweet_idx}] @grok tweet | replies={reply_count} | {text_preview}…")

                if tweet_url is None:
                    print(f"  [{tweet_idx}] Could not get tweet URL — skipping.")
                    skipped += 1
                    continue

                # ── Already has replies: check if we commented → halt if so
                if reply_count > 0:
                    already = self._already_commented_by_me(tweet_url)
                    if already:
                        print(f"  [{tweet_idx}] We already commented — halting.\n")
                        halted = True
                        break
                    # Has replies but NOT from us — comment anyway
                    print(f"  [{tweet_idx}] Has {reply_count} reply/replies but not ours — commenting.")

                # ── Post the comment
                if self._post_comment(tweet_url, tweet_idx):
                    commented += 1
                else:
                    skipped += 1

                time.sleep(delay_between)

            if halted:
                break

            if new_found == 0:
                print("No new tweets found after scroll — feed exhausted.")
                break

            print(f"\n  Scrolling… (round {scroll_round + 1})\n")
            self.page.evaluate("window.scrollBy(0, window.innerHeight * 3)")
            time.sleep(2.5)

        self._stop()

        print("=" * 70)
        print("DONE")
        print("=" * 70)
        print(f"  Keyword    : {self.KEYWORD}")
        print(f"  Comment    : {self.COMMENT}")
        print(f"  Commented  : {commented}")
        print(f"  Skipped    : {skipped}")
        print(f"  Halted     : {'Yes — hit an already-commented @grok tweet' if halted else 'No (reached end of feed)'}")
        print("=" * 70 + "\n")

        return {"commented": commented, "skipped": skipped, "halted": halted}


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    commenter = GrokCommenter(profile_dir="./twitter_browser_profile")

    # First time only — uncomment and run once:
    # commenter.setup_first_time()

    commenter.run(
        username="Anish81940",   # optional — auto-detected from profile
        headless=False,
        delay_between=3.0,
        max_scrolls=30,
    )


if __name__ == "__main__":
    main()
