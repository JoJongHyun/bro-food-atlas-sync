"""No network: verify only TVWiki source-listed drama episodes become buttons."""
from sync_tvwiki_episodes import parse_episodes, valid_work_url

WORK = "12640"
BODY = """
<!-- old deactivated markup -->
<div id="other_list">
  <h2>전체회차</h2>
  <ul>
    <li class="searchText 문무 2화" data-ep-idx="406792138">
      <a href="https://tvwiki60.net/drama/12640/406792138" class="img ep-link"><img src="thumb.png"></a>
      <a href="https://tvwiki60.net/drama/12640/406792138" class="title on ep-link">문무 2화</a>
    </li>
    <li class="searchText 문무 1화" data-ep-idx="406792026">
      <a href="https://tvwiki60.net/drama/12640/406792026" class="title on ep-link">문무 1화</a>
    </li>
    <li><a href="https://tvwiki60.net/drama/99999/406792026" class="title ep-link">other 3화</a></li>
    <li><a href="https://untrusted.example/drama/12640/3" class="title ep-link">other 3화</a></li>
  </ul>
</div>
"""
out = parse_episodes(BODY, WORK)
assert [x["number"] for x in out] == [1, 2], out
assert out[1]["pageUrl"] == "https://tvwiki60.net/drama/12640/406792138"
assert parse_episodes('<div id="nothing"></div>', WORK) is None
assert valid_work_url("http://tvwiki60.net/drama/12640/2") == ""
print("TVWiki public episode parsing: OK")
