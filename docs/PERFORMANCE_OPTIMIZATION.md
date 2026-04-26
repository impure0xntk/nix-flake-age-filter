# Performance Optimization Plan for nix-flake-age-filter

**Created**: 2026-04-26
**Status**: Partially Implemented

## Problem Statement

When a `flake.lock` contains 10+ inputs, the current implementation quickly exhausts GitHub API rate limits:

- **Unauthenticated**: 60 requests/hour per IP
- **Authenticated**: 5,000 requests/hour per user

Each input requires 1-2 API calls (resolve ref, get commit), so 10 inputs = 10-20 requests.

## Implemented Optimizations

### 1. Pluggable Backend System (Completed)
- **subprocess backend**: Uses `git` CLI (reliable, widely available)
- **pygit2 backend**: Uses `pygit2` library (faster than subprocess)
- **github backend**: Uses GitHub REST API v3 (fastest for GitHub repos)
- **auto backend**: Automatically selects best available backend

### 2. Parallel Execution (Completed)
- Uses `ThreadPoolExecutor` for concurrent input processing
- Configurable via `--parallel N` (default: 4, 0=serial)
- Significantly reduces total execution time for multiple inputs

### 3. GitHub Token Support (Completed)
- `--github-token` CLI option or `GITHUB_TOKEN` environment variable
- Increases rate limit from 60 to 5,000 requests/hour

## Architecture Analysis

### Current Backend System

```
backends/
├── base.py           # Abstract interface (GitBackend)
├── github_api_backend.py  # REST API (fast but rate-limited)
├── subprocess_backend.py  # git CLI (reliable but slower)
├── pygit2_backend.py     # libgit2 (fast, requires dependency)
└── registry.py            # Backend registration and lookup
```

### Current Flow (per input)

```
flake.lock input → parse URL → backend.get_commit_timestamp()
                                ↓
                    GitHub URL? → API call (with token if available)
                    Non-GitHub? → git fetch + log (via backend)
```

## Future Optimization Plans (Priority Order)

### Plan 1: GitHub API Conditional Requests + ETag Cache (P0 - High)

**Problem**: Every API call consumes rate limit, even for unchanged data.

**Solution**: Implement HTTP conditional requests using ETag/Last-Modified headers.

#### How It Works

GitHub API returns `ETag` and `Last-Modified` headers with every response:
```http
HTTP/2 200
ETag: "a3f2b1c4d5e6"
Last-Modified: Wed, 25 Oct 2026 14:00:00 GMT
```

Subsequent requests with these headers:
```http
GET /repos/owner/repo/commits/sha
If-None-Match: "a3f2b1c4d5e6"
```

If unchanged, GitHub returns **304 Not Modified** — **this does NOT count against rate limit**.

#### Expected Impact

- **Rate limit consumption**: 10 inputs → 0-10 requests (depending on cache freshness)
- **Repeated runs**: Near-zero API calls if inputs unchanged
- **Cache hit rate**: Expected 80-90% for daily usage

#### Files to Modify

- `github_api_backend.py`: Add `GitHubCache` class and conditional request logic
- New file: `cache.py` (optional, for shared cache utilities)

---

### Plan 2: GitHub GraphQL API Batch Queries (P1 - Medium)

**Problem**: REST API requires separate requests for each repository.

**Solution**: Use GraphQL API to fetch multiple repositories in one query.

#### How It Works

GraphQL allows querying multiple resources in a single request:
```graphql
query {
  repo1: repository(owner: "NixOS", name: "nixpkgs") {
    defaultBranchRef {
      target { ... on Commit { oid committedDate } }
    }
  }
  repo2: repository(owner: "nix-community", name: "nixpkgs") {
    defaultBranchRef {
      target { ... on Commit { oid committedDate } }
    }
  }
}
```

#### Expected Impact

- **Rate limit**: 50-70% reduction vs REST API
- **Latency**: Single round-trip vs 10-20 sequential requests

#### Files to Create/Modify

- New: `graphql_backend.py`
- `backends/__init__.py`: Register GraphQL backend
- `backends/registry.py`: Add batch operation support

---

### Plan 3: asyncio Subprocess Parallelization (P2 - Low)

**Problem**: Current `ThreadPoolExecutor` doesn't scale well for I/O-bound operations.

**Solution**: Use `asyncio.create_subprocess_exec` for true async I/O.

#### Expected Impact

- **Concurrency**: 50+ parallel connections (vs thread pool limit ~10)
- **Performance**: 5-10x faster for non-GitHub repos

#### Files to Modify

- `subprocess_backend.py`: Add async methods
- `parallel.py`: Add `execute_parallel_async`
- `cli/`: Update to support async execution

---

### Plan 4: Shallow Fetch Optimization (P3 - Low)

**Problem**: Current implementation creates fresh temp directories and fetches repeatedly.

**Solution**: Optimize temporary repo management and fetch strategy.

#### Optimization Ideas

1. **Blobless Clone (Git 2.22+)**
   ```bash
   git clone --filter=blob:none --bare <url> repo.git
   ```
   For commit timestamp checking, we only need commit metadata, not file contents.

2. **Single-Branch Fetch**
   ```bash
   git fetch --depth=100 --single-branch origin main
   ```

#### Expected Impact

- **Network**: Blobless = 10x smaller transfers
- **Time**: 20-30% faster per input

## Implementation Roadmap

### Phase 1: Immediate (Completed)
- ✅ Pluggable backend system (subprocess, pygit2, github, auto)
- ✅ Parallel execution with ThreadPoolExecutor
- ✅ GitHub token support

### Phase 2: Short-term (Planned)
| Task | File | Effort |
|------|------|--------|
| ETag cache implementation | `github_api_backend.py` | 4h |
| Cache storage (JSONL) | New: `cache.py` | 2h |
| CLI `--cache-dir` option | `cli/` | 1h |
| Tests for cache | `tests/` | 2h |

### Phase 3: Medium-term (Planned)
| Task | File | Effort |
|------|------|--------|
| GraphQL backend skeleton | New: `graphql_backend.py` | 4h |
| Batch query construction | `graphql_backend.py` | 3h |
| Registry batch support | `registry.py` | 2h |
| Tests for GraphQL | `tests/` | 3h |

## Additional Considerations

### Token Authentication

Even with optimizations, providing a GitHub token significantly improves limits:
```bash
# Environment variable
export GITHUB_TOKEN=ghp_xxxx

# Or in CLI
nix-flake-age verify --github-token $GITHUB_TOKEN flake.lock
```

### Offline Mode

With ETag cache, repeated runs can work offline (if cache is warm):
```bash
nix-flake-age verify --offline --cache-dir ~/.cache/nix-flake-age-filter flake.lock
```

### CI/CD Integration

For CI pipelines, pre-warm cache in a previous step:
```yaml
# GitHub Actions
- name: Warm flake age cache
  run: nix-flake-age verify --warm-cache flake.lock
  
- name: Check flake ages
  run: nix-flake-age verify --min-age 7 flake.lock
```

## References

### GitHub API
- [Best Practices for REST API](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)
- [Rate Limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)
- [GraphQL API](https://docs.github.com/en/graphql)

### Python Async
- [asyncio subprocess](https://docs.python.org/3/library/asyncio-subprocess.html)

### Git Optimization
- [Git partial clone](https://git-scm.com/docs/git-partial-clone)

### Related Projects
- [npm min-release-age](https://docs.npmjs.com/cli/v11/using-npm/config#min-release-age) - inspiration
- [Renovate bot](https://github.com/renovatebot/renovate) - batch GitHub API patterns
