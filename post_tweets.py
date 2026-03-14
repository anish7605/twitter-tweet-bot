"""
Twitter Poster - Concurrent Async Version
Uses playwright.async_api with asyncio.gather so all browser windows
post truly in parallel. Persistent profile cloning preserves your login.
"""

import asyncio
import math
import shutil
from pathlib import Path
from playwright.async_api import async_playwright
import grok_prompts as gp


class ConcurrentTwitterPoster:

    def __init__(self, profile_dir: str = "./twitter_browser_profile"):
        self.profile_dir = profile_dir

    # ── First-time login ───────────────────────────────────────────────────

    def setup_first_time(self):
        """Run once. Opens a real browser so you can log in manually."""
        from playwright.sync_api import sync_playwright

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

    # ── Profile cloning ────────────────────────────────────────────────────

    _CHROME_SKIP = {
        "SingletonLock", "SingletonSocket", "SingletonCookie",
        "RunningChromeVersion", "lockfile", "LOG", "LOG.old",
    }

    def _clone_profiles(self, num_workers: int) -> list[str]:
        master = Path(self.profile_dir)
        if not master.exists():
            raise FileNotFoundError(
                f"Profile not found: {self.profile_dir}\n"
                "Run setup_first_time() first."
            )

        def _ignore(src, names):
            return [n for n in names if n in self._CHROME_SKIP]

        worker_dirs = []
        for i in range(num_workers):
            dest = Path(f"{self.profile_dir}_worker_{i}")
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(master, dest, ignore=_ignore, symlinks=False)
            worker_dirs.append(str(dest))
            print(f"  Cloned profile -> {dest.name}")

        return worker_dirs

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _split(tweets: list, n: int) -> list[list]:
        chunk_size = math.ceil(len(tweets) / n)
        return [tweets[i: i + chunk_size] for i in range(0, len(tweets), chunk_size)]

    # ── Async worker ───────────────────────────────────────────────────────

    async def _post_one(self, page, worker_id: int, tweet_text: str, wait_after: int = 3) -> bool:
        try:
            if "home" not in page.url:
                await page.goto("https://twitter.com/home", wait_until="domcontentloaded")
                await asyncio.sleep(2)

            tweet_box = None
            for sel in [
                'div[data-testid="tweetTextarea_0"]',
                'div[role="textbox"][data-testid="tweetTextarea_0"]',
                'div[aria-label="Post text"]',
            ]:
                try:
                    tweet_box = await page.wait_for_selector(sel, timeout=5_000)
                    if tweet_box:
                        break
                except Exception:
                    continue

            if not tweet_box:
                await page.screenshot(path=f"debug_worker_{worker_id}.png")
                raise RuntimeError("Could not find tweet compose box.")

            await tweet_box.click()
            await asyncio.sleep(0.5)
            await tweet_box.type(tweet_text, delay=50)
            await asyncio.sleep(1)

            post_btn = None
            for sel in [
                'div[data-testid="tweetButtonInline"]',
                'button[data-testid="tweetButtonInline"]',
                'div[data-testid="tweetButton"]',
            ]:
                try:
                    post_btn = await page.wait_for_selector(sel, timeout=3_000)
                    if post_btn:
                        break
                except Exception:
                    continue

            if not post_btn:
                raise RuntimeError("Could not find Post button.")

            await post_btn.click()
            await asyncio.sleep(wait_after)

            preview = tweet_text[:60] + ("..." if len(tweet_text) > 60 else "")
            print(f"  [Worker {worker_id}] OK  {preview}")
            return True

        except Exception as exc:
            print(f"  [Worker {worker_id}] FAIL  {exc}")
            return False

    async def _run_worker(
        self,
        pw,
        worker_id: int,
        profile_dir: str,
        chunk: list[str],
        delay_between: int,
        headless: bool,
    ) -> dict:
        """One worker: opens its own persistent context and posts its chunk."""
        ok = fail = 0
        ctx = await pw.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=headless,
            args=["--disable-blink-features=AutomationControlled",
                  "--disable-dev-shm-usage"],
            viewport={"width": 1280, "height": 800},
        )
        try:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await page.goto("https://twitter.com/home", wait_until="domcontentloaded")
            await asyncio.sleep(2)

            if "login" in page.url:
                raise RuntimeError(f"Worker {worker_id}: not logged in — re-run setup_first_time()")

            print(f"  [Worker {worker_id}] Ready — {len(chunk)} tweets assigned")

            for idx, tweet in enumerate(chunk, 1):
                print(f"  [Worker {worker_id}] [{idx}/{len(chunk)}] Posting...")
                text = tweet + " Follow & subscribe to my Patreon for exclusive tech and coding content! - https://t.co/nQRZljSpYD"
                if await self._post_one(page, worker_id, text, wait_after=3):
                    ok += 1
                else:
                    fail += 1

                if idx < len(chunk):
                    await asyncio.sleep(delay_between)

        finally:
            await ctx.close()

        print(f"  [Worker {worker_id}] Done — ok={ok} fail={fail}")
        return {"ok": ok, "fail": fail}

    # ── Public entry point ─────────────────────────────────────────────────

    async def _post_tweets_async(
        self,
        tweets: list[str],
        num_sessions: int,
        delay_between: int,
        headless: bool,
    ) -> dict:
        num_sessions = max(1, min(num_sessions, 5))
        chunks       = self._split(tweets, num_sessions)

        print(f"\n{'=' * 70}")
        print("Concurrent Twitter Poster  (async, persistent profiles)")
        print(f"  Total tweets  : {len(tweets)}")
        print(f"  Sessions      : {num_sessions}")
        print(f"  Tweets/session: ~{math.ceil(len(tweets) / num_sessions)}")
        print(f"  Delay/tweet   : {delay_between}s per worker")
        print(f"{'=' * 70}\n")

        print("Cloning browser profiles...")
        worker_dirs = self._clone_profiles(num_sessions)
        print()

        async with async_playwright() as pw:
            tasks = [
                self._run_worker(pw, i, profile, chunk, delay_between, headless)
                for i, (profile, chunk) in enumerate(zip(worker_dirs, chunks))
            ]
            # All workers run truly in parallel
            all_results = await asyncio.gather(*tasks)

        total_ok   = sum(r["ok"]   for r in all_results)
        total_fail = sum(r["fail"] for r in all_results)

        print(f"\n{'=' * 70}")
        print("COMPLETE")
        print(f"{'=' * 70}")
        for i, r in enumerate(all_results):
            print(f"  Worker {i}: ok={r['ok']}  fail={r['fail']}")
        print(f"{'─' * 70}")
        print(f"  Total: ok={total_ok}  fail={total_fail}  ({len(tweets)} tweets)")
        print(f"{'=' * 70}\n")

        return {"successful": total_ok, "failed": total_fail, "total": len(tweets)}

    def post_tweets(
        self,
        tweets: list[str],
        num_sessions: int = 4,
        delay_between: int = 10,
        headless: bool = False,
    ) -> dict:
        """Synchronous wrapper — call this from main() as normal."""
        return asyncio.run(
            self._post_tweets_async(tweets, num_sessions, delay_between, headless)
        )


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    # news = gp.docker_kubernetes_prompts + gp.linux_prompts + gp.pentesting_prompts + gp.scrum_prompts \
    #     + gp.sysadmin_prompts + gp.systems_programming_prompts + gp.cloud_computing_prompts
    
    prompts = gp.handles
    poster = ConcurrentTwitterPoster(profile_dir="./twitter_browser_profile")

    # First time only — uncomment and run once:
    poster.setup_first_time()

    poster.post_tweets(
        tweets=prompts,
        num_sessions=5,      # 3-5 parallel windows
        delay_between=10,
        headless=False,
    )


if __name__ == "__main__":
    main()
