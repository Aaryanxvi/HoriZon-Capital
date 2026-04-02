"""Reddit client for fetching posts from financial subreddits via PRAW."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial

import praw

from app.config import settings
from app.core.logging import get_logger

logger = get_logger("sentiment.reddit")

DEFAULT_SUBREDDITS: list[str] = ["IndiaInvestments", "stocks", "wallstreetbets"]

# Shared thread-pool for running synchronous PRAW calls without blocking the
# async event loop.  A small pool is sufficient -- Reddit API is rate-limited.
_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="reddit")


class RedditClient:
    """Wraps the synchronous PRAW library in an async-friendly interface.

    PRAW does not support ``asyncio`` natively, so every call is dispatched to
    a thread-pool executor.
    """

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        self.client_id = client_id or settings.reddit_client_id
        self.client_secret = client_secret or settings.reddit_client_secret
        self.user_agent = user_agent or settings.reddit_user_agent
        self._reddit: praw.Reddit | None = None

    def _get_reddit(self) -> praw.Reddit:
        """Lazy-initialise the PRAW Reddit instance (called inside the executor)."""
        if self._reddit is None:
            self._reddit = praw.Reddit(
                client_id=self.client_id,
                client_secret=self.client_secret,
                user_agent=self.user_agent,
            )
        return self._reddit

    # ------------------------------------------------------------------
    # Synchronous helpers (run inside the thread-pool)
    # ------------------------------------------------------------------

    def _fetch_posts_sync(
        self,
        symbol: str,
        subreddits: list[str],
        limit: int,
    ) -> list[dict]:
        """Blocking implementation that queries Reddit via PRAW."""
        reddit = self._get_reddit()
        base_symbol = symbol.split(".")[0]
        results: list[dict] = []

        for sub_name in subreddits:
            try:
                subreddit = reddit.subreddit(sub_name)
                for post in subreddit.search(
                    base_symbol,
                    sort="new",
                    time_filter="month",
                    limit=limit,
                ):
                    results.append(
                        {
                            "title": post.title,
                            "body": (post.selftext or "")[:2000],
                            "score": post.score,
                            "num_comments": post.num_comments,
                            "created_utc": post.created_utc,
                            "subreddit": sub_name,
                        }
                    )
            except Exception as exc:
                logger.warning(
                    "reddit_subreddit_error",
                    subreddit=sub_name,
                    symbol=symbol,
                    error=str(exc),
                )

        return results

    # ------------------------------------------------------------------
    # Async public API
    # ------------------------------------------------------------------

    async def fetch_posts(
        self,
        symbol: str,
        subreddits: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Fetch Reddit posts mentioning *symbol* from the given subreddits.

        Parameters
        ----------
        symbol:
            Ticker symbol (exchange suffix is stripped automatically).
        subreddits:
            List of subreddit names to search.  Defaults to
            ``["IndiaInvestments", "stocks", "wallstreetbets"]``.
        limit:
            Maximum posts per subreddit.

        Returns
        -------
        list[dict]
            Each dict contains ``title``, ``body``, ``score``,
            ``num_comments``, ``created_utc``, and ``subreddit``.
        """
        if not self.client_id or not self.client_secret:
            return []

        subreddits = subreddits or DEFAULT_SUBREDDITS

        loop = asyncio.get_running_loop()
        posts = await loop.run_in_executor(
            _executor,
            partial(self._fetch_posts_sync, symbol, subreddits, limit),
        )

        logger.info(
            "reddit_fetched",
            symbol=symbol,
            post_count=len(posts),
            subreddits=subreddits,
        )
        return posts
