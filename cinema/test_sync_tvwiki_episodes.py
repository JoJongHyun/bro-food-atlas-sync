"""No network: verify only TVWiki source-listed drama episodes become buttons."""
from sync_tvwiki_episodes import parse_episodes, valid_work_url

WORK = "12640"
BODY = """
<!-- old deactivated markup -->
<div id="other_list">
  <h2>전체회차</h2>
  <ul>
    <li class="searchText 문무 2화" data-ep-idx="406792138">
      <a href="https://tvwiki61.net/drama/12640/406792138" class="img ep-link"><img src="thumb.png"></a>
      <a href="https://tvwiki61.net/drama/12640/406792138" class="title on ep-link">문무 2화</a>
    </li>
    <li class="searchText 문무 1화" data-ep-idx="406792026">
      <a href="https://tvwiki61.net/drama/12640/406792026" class="title on ep-link">문무 1화</a>
    </li>
    <li><a href="https://tvwiki61.net/drama/99999/406792026" class="title ep-link">other 3화</a></li>
    <li><a href="https://untrusted.example/drama/12640/3" class="title ep-link">other 3화</a></li>
  </ul>
</div>
"""
out = parse_episodes(BODY, WORK)
assert [x["number"] for x in out] == [1, 2], out
assert out[1]["pageUrl"] == "https://tvwiki61.net/drama/12640/406792138"
assert parse_episodes('<div id="nothing"></div>', WORK) is None
assert valid_work_url("http://tvwiki61.net/drama/12640/2") == ""
ENT_BODY = """
<div id="other_list"><h2>전체회차</h2><ul>
  <li class="searchText TV 동물농장 1296화">
    <a href="https://tvwiki61.net/ent/1703/406792162" class="title on ep-link">TV 동물농장 1296화</a></li>
  <li class="searchText TV 동물농장 1295화">
    <a href="https://tvwiki61.net/ent/1703/406790298" class="title on ep-link">TV 동물농장 1295화</a></li>
  <li><a href="https://tvwiki61.net/drama/1703/406792162" class="title ep-link">wrong route 1297화</a></li>
  <li><a href="https://tvwiki61.net/ent/1999/406792162" class="title ep-link">wrong work 1298화</a></li>
</ul></div>
"""
ent_episodes = parse_episodes(ENT_BODY, "1703", route="ent")
assert [x["number"] for x in ent_episodes] == [1295, 1296], ent_episodes
assert ent_episodes[-1]["pageUrl"] == "https://tvwiki61.net/ent/1703/406792162"
assert valid_work_url("https://tvwiki61.net/ent/1703/406792162")
assert [e["number"] for e in parse_episodes(ENT_BODY, "1703", route="drama")] == [1297]  # route filtering is independent
from sync_tvwiki_recent import parse_page
ENT_INDEX = """<div id="list_type"><ul><li><div class="box">
  <a href="https://tvwiki61.net/ent/1703/406792162" class="title2">TV 동물농장</a>
  <img src="https://image.tmdb.org/t/p/w500/poster.jpg"></div></li></ul></div>"""
assert parse_page(ENT_INDEX, "예능", "ent")[0]["id"] == "tvwiki-ent-1703"
print("TVWiki public drama/entertainment episode parsing: OK")

# Domain cutover: historical verified links are allowed but canonicalized.
assert valid_work_url("https://tvwiki60.net/ent/1703/406792162") == "https://tvwiki61.net/ent/1703/406792162"
assert valid_work_url("https://untrusted.example/ent/1703/406792162") == ""
from sync_tvwiki_kor import valid_movie_url, work_id
assert valid_movie_url("https://tvwiki60.net/kor_movie/35812/406792475") == "https://tvwiki61.net/kor_movie/35812/406792475"
assert work_id("https://tvwiki60.net/kor_movie/35812/406792475") == "35812"
from sync_catalog import migrate_tvwiki_hosts
sample={"items":[{"id":"tvwiki-drama-1","category":"드라마",
  "tvwikiPage":"https://tvwiki60.net/drama/1/99",
  "tvwikiEpisodeCheckedAt":"2026-11-18T00:00:00+00:00",
  "episodes":[{"number":1,"pageUrl":"https://tvwiki60.net/drama/1/98"},
             {"number":2,"pageUrl":"https://tvwiki60.net/drama/1/99"}]}]}
count=migrate_tvwiki_hosts(sample)
assert count == 3, count
assert sample["items"][0]["tvwikiPage"] == "https://tvwiki61.net/drama/1/99"
assert sample["items"][0]["episodes"][0]["number"] == 1
assert sample["items"][0]["episodes"][1]["pageUrl"] == "https://tvwiki61.net/drama/1/99"
assert sample["items"][0]["tvwikiEpisodeCheckedAt"] == ""
assert migrate_tvwiki_hosts(sample) == 0
print("TVWiki domain migration regression tests: OK")
