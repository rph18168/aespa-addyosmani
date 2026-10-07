import unittest
from datetime import datetime, timedelta, timezone

from aespa_digest.models import Article, FeedConfig, SourceConfig
from aespa_digest.qualification import qualify_articles
from aespa_digest.sources import FeedError, MAX_FEED_BYTES, fetch_feed, parse_feed


class FeedParsingTests(unittest.TestCase):
    def test_parses_rss_entry_and_strips_markup(self):
        feed = FeedConfig(
            name="Soompi",
            url="https://news.google.com/rss/search?q=aespa",
            fallback_domain="soompi.com",
        )
        payload = """
        <rss version="2.0">
          <channel>
            <item>
              <title>aespa announces a new release</title>
              <description><![CDATA[<p>aespa <b>shared</b> new plans.</p>]]></description>
              <link>https://www.soompi.com/article/123</link>
              <pubDate>Sat, 29 Aug 2026 00:00:00 +0000</pubDate>
              <source url="https://www.soompi.com">Soompi</source>
            </item>
          </channel>
        </rss>
        """.encode("utf-8")

        articles = parse_feed(payload, feed)

        self.assertEqual(len(articles), 1)
        article = articles[0]
        self.assertEqual(article.title, "aespa announces a new release")
        self.assertEqual(article.summary, "aespa shared new plans.")
        self.assertEqual(article.source_name, "Soompi")
        self.assertEqual(article.source_domain, "www.soompi.com")
        self.assertEqual(article.published_at.tzinfo, timezone.utc)

    def test_parses_atom_entry_and_uses_fallback_domain(self):
        feed = FeedConfig(
            name="Billboard",
            url="https://feeds.example.test/aespa.atom",
            fallback_domain="billboard.com",
        )
        payload = """
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>에스파 returns to the stage</title>
            <summary>The group announced a new appearance.</summary>
            <link rel="alternate" href="https://www.billboard.com/music/news/aespa" />
            <updated>2026-08-29T01:30:00Z</updated>
          </entry>
        </feed>
        """.encode("utf-8")

        articles = parse_feed(payload, feed)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].source_name, "Billboard")
        self.assertEqual(articles[0].source_domain, "billboard.com")
        self.assertEqual(
            articles[0].published_at,
            datetime(2026, 8, 29, 1, 30, tzinfo=timezone.utc),
        )

    def test_fetch_feed_rejects_payload_over_size_limit(self):
        feed = FeedConfig(
            name="Test",
            url="https://feeds.example.test/aespa.xml",
            fallback_domain="example.test",
        )

        def oversized_fetcher(url, timeout_seconds):
            return b"x" * (MAX_FEED_BYTES + 1)

        with self.assertRaises(FeedError):
            fetch_feed(feed, timeout_seconds=1, fetch_bytes=oversized_fetcher)


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc)
        self.sources = SourceConfig(
            keywords=("aespa", "에스파"),
            trusted_domains=("soompi.com", "billboard.com"),
            feeds=(),
        )

    def article(self, **overrides):
        values = {
            "title": "aespa shares an update",
            "summary": "The group shared new plans.",
            "link": "https://www.soompi.com/article/123",
            "source_name": "Soompi",
            "source_domain": "www.soompi.com",
            "published_at": self.now - timedelta(hours=1),
        }
        values.update(overrides)
        return Article(**values)

    def test_keeps_recent_relevant_trusted_articles_sorted_newest_first(self):
        older = self.article(
            title="aespa older update",
            link="https://www.soompi.com/article/older",
            published_at=self.now - timedelta(hours=2),
        )
        newer = self.article(
            title="aespa newest update",
            link="https://www.billboard.com/article/newer",
            source_domain="billboard.com",
            published_at=self.now - timedelta(minutes=10),
        )

        result = qualify_articles(
            [older, newer],
            self.sources,
            now=self.now,
            lookback_hours=36,
            max_articles=20,
        )

        self.assertEqual([article.title for article in result], ["aespa newest update", "aespa older update"])

    def test_drops_untrusted_irrelevant_old_future_and_undated_articles(self):
        candidates = [
            self.article(source_domain="unknown.example"),
            self.article(title="another group update"),
            self.article(
                title="aespa old update",
                published_at=self.now - timedelta(hours=37),
            ),
            self.article(
                title="aespa future update",
                published_at=self.now + timedelta(hours=3),
            ),
            self.article(title="aespa undated update", published_at=None),
        ]

        result = qualify_articles(
            candidates,
            self.sources,
            now=self.now,
            lookback_hours=36,
            max_articles=20,
        )

        self.assertEqual(result, [])

    def test_deduplicates_urls_and_titles_and_applies_maximum(self):
        same_url = self.article(
            title="aespa shares an update",
            link="https://www.soompi.com/article/123?utm_source=rss",
            published_at=self.now - timedelta(minutes=30),
        )
        same_title = self.article(
            title="  AESPA shares an update  ",
            link="https://www.billboard.com/article/456",
            source_domain="billboard.com",
            published_at=self.now - timedelta(minutes=20),
        )
        another = self.article(
            title="aespa second update",
            link="https://www.soompi.com/article/789",
            published_at=self.now - timedelta(minutes=10),
        )

        result = qualify_articles(
            [same_url, same_title, another],
            self.sources,
            now=self.now,
            lookback_hours=36,
            max_articles=1,
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].title, "aespa second update")

    def qualify(self, articles, **overrides):
        options = dict(now=self.now, lookback_hours=36, max_articles=20)
        options.update(overrides)
        return qualify_articles(articles, self.sources, **options)

    def replay_titles(self, titles):
        # Verbatim digest titles; URL/domain/times are controlled test inputs.
        return [self.article(title=title, summary="",
                             link=f"https://www.soompi.com/article/replay-{index}",
                             published_at=self.now - timedelta(minutes=index))
                for index, title in enumerate(titles)]

    def test_october_5_and_6_multilingual_la_reports_form_one_event(self):
        # Gmail 1a109fdfcea93edc (Oct 5), 1a10f51e0b039c7d (Oct 6).
        rows = (
            ("Aespa's LA concert sells out, showcasing 'metallic taste' performances - 조선일보", '2026-10-05T10:19:00+08:00'),
            ('aespa、LA公演は視界制限席まで完売 - 조선일보', '2026-10-05T10:12:00+08:00'),
            ("에스파, LA 콘서트 시야제한석까지 완판..독보적 '쇠 맛' 통했다 - OSEN", '2026-10-05T10:12:00+08:00'),
            ('‘뜨겁다’ 에스파, LA 콘서트 시야제한석까지 완판 - 스포츠서울', '2026-10-05T09:27:00+08:00'),
            ('에스파, LA 콘서트 성료...시야제한석까지 전석매진 - specialtimes.co.kr', '2026-10-05T09:18:00+08:00'),
            ('에스파, 세 번째 LA 단독 콘서트 성료...인튜이트 돔 매진 - 비즈엔터', '2026-10-05T09:17:00+08:00'),
            ('에스파, LA 콘서트 시야제한석까지 전석 매진...글로벌 티켓 파워 - 뉴스엔', '2026-10-05T09:06:00+08:00'),
            ('에스파, LA 콘서트 시야제한석까지 전석매진 기염 - 싱글리스트', '2026-10-05T09:05:00+08:00'),
            ('에스파, 미국 LA 인튜이트 돔 단독 콘서트 성료 - bntnews.co.kr', '2026-10-05T09:02:00+08:00'),
            ('“LA가 들썩였다”...에스파, 초대형 공연장 꽉 채운 글로벌 인기 - ppss.kr', '2026-10-04T14:39:00+08:00'),
            ('에스파, LA 인튜이트 돔까지 채웠다 “다시 올 수 있어서 너무 좋았다” - TopStarNews', '2026-10-05T09:04:00+08:00'),
            ('【韓流】aespaが全席完売でLAツアー終了 オークランド、シアトルと続く - Infoseek', '2026-10-06T08:19:00+08:00'),
            ('aespa LA concert — Sells Out Intuit Dome with Iron Taste Vibe - The Korea Daily', '2026-10-06T01:02:00+08:00'),
            ('“World Tour Going Strong” Aespa Sells Out Every Seat at LA Concert, Including Restricted-View Sections - 매일경제', '2026-10-05T16:08:00+08:00'),
            ('“世界巡演顺利进行”aespa,LA演唱会连视野受限席位也全部售罄 - 매일경제', '2026-10-05T16:08:00+08:00'),
            ('「ワールドツアー快調」エスパ、ロサンゼルス(L.A.)公演は見切れ席まで全席完売 - 매일경제', '2026-10-05T16:08:00+08:00'),
            ('에스파, LA 단독 콘서트 전석 매진 - 전국매일신문', '2026-10-05T15:53:00+08:00'),
            ('에스파, 美 LA 콘서트 전석 매진...월드투어 성황 - 대구신문', '2026-10-05T13:44:00+08:00'),
            ('에스파, LA 대형 공연장 세 번째 매진... 인튜이트 돔도 채웠다 - edaily.co.kr', '2026-10-05T13:42:00+08:00'),
            ('aespa世巡洛杉矶站演出圆满落幕 - 韩联社', '2026-10-05T13:39:00+08:00'),
        )
        articles = [self.article(
            title=title, summary="",
            link=f"https://www.soompi.com/article/replay-{index}",
            published_at=datetime.fromisoformat(stamp))
            for index, (title, stamp) in enumerate(rows)]
        # Replay each issue at its real generation time, then both together.
        self.assertEqual(self.qualify(articles[:11], now=datetime.fromisoformat(
            "2026-10-05T10:56:00+08:00")), [articles[0]])
        self.assertEqual(self.qualify(articles[11:], now=datetime.fromisoformat(
            "2026-10-06T11:46:00+08:00")), [articles[11]])
        self.assertEqual(self.qualify(articles, now=datetime.fromisoformat(
            "2026-10-06T11:46:00+08:00"), lookback_hours=48), [articles[11]])

    def test_hearts2hearts_sister_group_is_not_aespa_subject(self):
        # Oct 6 Gmail 1a10f51e0b039c7d: verbatim title and displayed summary.
        article = self.article(
            title='少女時代・aespaの妹!ミラクルキュートなK-POP新人ガールズアイドルグループ Hearts2Hearts、日本デビュー曲「ICONIC HEART」韓国語バージョンでリリース―韓国音楽番組でのパフォーマンスも - kanstarpress.com',
            summary='少女時代・aespaの妹!ミラクルキュートなK-POP新人ガールズアイドルグループ Hearts2Hearts、日本デビュー曲「ICONIC HEART」韓国語バージョンでリリース―韓国音楽番組でのパフォーマンスも kanstarpress.com',
        )
        self.assertEqual(self.qualify([article]), [])

    def test_athlete_nickname_is_not_member_identity(self):
        # Oct 5 Gmail 1a109fdfcea93edc: verbatim title. Original displayed
        # summary has no aespa; the enriched summary is a synthetic adversarial
        # input, not a claim about the inaccessible pre-render feed payload.
        for summary in ("Track Star Kim Min-ji, Dubbed the 'Karina of Athletics,' Reveals Unexpected Charms: A Slim Silhouette and Defined Abs Captivate Fans 재경일보",
                        "Kim Min-ji is compared to aespa's Karina."):
            with self.subTest(summary=summary):
                self.assertEqual(self.qualify([self.article(
                    title="Track Star Kim Min-ji, Dubbed the 'Karina of Athletics,' Reveals Unexpected Charms: A Slim Silhouette and Defined Abs Captivate Fans - 재경일보", summary=summary)]), [])

    def test_summary_only_mentions_and_substrings_are_rejected(self):
        for title in ("Hearts2Hearts releases ICONIC HEART", "notaespa archive",
                      "aespa123 fan account", "The next aespa debuts"):
            with self.subTest(title=title):
                self.assertEqual(self.qualify([self.article(
                    title=title, summary="The article also mentions aespa.")]), [])

    def test_member_headline_requires_same_member_group_affiliation(self):
        title = "'금발여신' 윈터, 군살 제로 '슬림핏 실루엣' 비결은 - 뉴시스"
        positive = self.article(title=title, summary="에스파 윈터가 사진을 공개했다.")
        self.assertEqual(self.qualify([positive]), [positive])
        for summary in ("Winter fashion inspired aespa.", "aespa's Karina shared photos."):
            self.assertEqual(self.qualify([self.article(title="Winter shares photos",
                                                       summary=summary)]), [])
        collaboration = self.article(title="aespa and Hearts2Hearts perform together")
        self.assertEqual(self.qualify([collaboration]), [collaboration])
        custom = SourceConfig(keywords=("Hearts2Hearts",),
                              trusted_domains=self.sources.trusted_domains, feeds=())
        self.assertEqual(qualify_articles([positive], custom, now=self.now,
                                         lookback_hours=36, max_articles=20), [])

    def test_review_health_and_growth_angles_are_not_sellout_duplicates(self):
        # Verbatim Oct 6 titles; summaries below are controlled identity context.
        titles = (
            'aespa LA concert — Sells Out Intuit Dome with Iron Taste Vibe - The Korea Daily',
            'aespa SYNK : COMPLæXITY Tour Review: Intuit Dome, LA - Sweety High',
            'aespa Winter Shingles Return: Intuit Dome LA Concert Oct. 3 : K-WAVE - en.koreaportal.com',
            'aespa Winter巡演期间高压透支体能罹生蛇 症状与预防攻略逐一看 - 香港01',
            '크립토닷컴→기아 포럼→인튜이트 돔...에스파, LA서 증명한 ‘계단식 성장’ - 스포츠동아',
        )
        articles = self.replay_titles(titles)
        self.assertEqual(self.qualify(articles), articles)
        growth = self.article(title='크립토닷컴→기아 포럼→인튜이트 돔...에스파, LA서 증명한 ‘계단식 성장’ - 스포츠동아', summary='크립토닷컴→기아 포럼→인튜이트 돔...에스파, LA서 증명한 ‘계단식 성장’ 스포츠동아 에스파, 월드투어 美 LA 콘서트 시야제한석까지 전석 매진 KBS 뉴스 에스파, LA 인튜이트 돔까지 채웠다 “다시 올 수 있어서 너무 좋았다” TopStarNews',
                              link="https://www.soompi.com/article/growth")
        sold_out = articles[0]
        self.assertEqual(self.qualify([sold_out, growth]), [sold_out, growth])

    def test_different_cities_show_dates_and_distant_reports_remain_separate(self):
        titles = ("aespa LA concert sold out Oct. 3",
                  "에스파 LA 콘서트 10월 3일 전석 매진",
                  "aespa LA concert sold out 2026-10-04",
                  "aespa Oakland concert sold out Oct. 3")
        articles = self.replay_titles(titles)
        self.assertEqual(self.qualify(articles), [articles[0], articles[2], articles[3]])
        undated = self.article(title="aespa LA concert sells out",
                               link="https://www.soompi.com/article/no-date")
        self.assertEqual(len(self.qualify([articles[0], undated])), 2)
        articles = self.replay_titles(("aespa LA concert sells out",
                                      "에스파 LA 콘서트 전석 매진",
                                      "エスパ LA公演 全席完売"))
        from dataclasses import replace
        articles[1] = replace(articles[1], published_at=self.now - timedelta(hours=47))
        articles[2] = replace(articles[2], published_at=self.now - timedelta(hours=49))
        self.assertEqual(self.qualify(articles, lookback_hours=96),
                         [articles[0], articles[2]])

    def test_exact_url_and_title_deduplication_independently(self):
        originals = self.replay_titles(("aespa first update", "aespa second update"))
        from dataclasses import replace
        duplicates = [replace(originals[0], title="aespa alternate headline",
                              link=originals[0].link + "?utm_source=rss#top",
                              published_at=self.now - timedelta(hours=1)),
                      replace(originals[1], title="  AESPA second update  ",
                              link="https://www.billboard.com/article/copy",
                              source_domain="billboard.com",
                              published_at=self.now - timedelta(hours=2))]
        self.assertEqual(self.qualify(originals + duplicates), originals)

    def test_event_deduplication_preserves_guards_and_limit(self):
        articles = self.replay_titles(("aespa LA concert sells out",
                                      "エスパ LA公演 全席完売",
                                      "aespa announces a new album"))
        from dataclasses import replace
        invalid = [replace(articles[0], source_domain="untrusted.example"),
                   replace(articles[0], link="https://soompi.com.evil.test/a"),
                   replace(articles[0], link="http://www.soompi.com/a"),
                   replace(articles[0], published_at=None),
                   replace(articles[0], published_at=self.now - timedelta(hours=37)),
                   replace(articles[0], published_at=self.now + timedelta(hours=3))]
        self.assertEqual(self.qualify(invalid), [])
        self.assertEqual(self.qualify(invalid + articles, max_articles=2),
                         [articles[0], articles[2]])


if __name__ == "__main__":
    unittest.main()
