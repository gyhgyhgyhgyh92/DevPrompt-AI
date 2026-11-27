const test = require('node:test')
const assert = require('node:assert/strict')

const {
  buildSourceList,
  isAllowedUpdateHost,
  sameManifest,
  manifestFingerprint,
  formatBytes,
} = require('../dist/updateSources.js')

const MANIFEST = `version: 0.3.0
files:
  - url: DevPromptAI-0.3.0-win-x64.exe
    sha512: abc+/def==
    size: 153597724
path: DevPromptAI-0.3.0-win-x64.exe
sha512: abc+/def==
releaseDate: '2026-11-27T12:00:00.000Z'
`

test('buildSourceList：镜像按序、GitHub 最后、末尾带斜杠', () => {
  const sources = buildSourceList()
  assert.deepEqual(
    sources.map((source) => source.id),
    ['ghfast', 'ghproxy', 'ghproxy-com', 'github'],
  )
  for (const source of sources) {
    assert.match(source.baseUrl, /\/$/)
    assert.match(source.baseUrl, /gyhgyhgyhgyh92\/DevPrompt-AI\/releases\/download\/updates\/$/)
  }
  assert.match(sources[0].baseUrl, /^https:\/\/ghfast\.top\/https:\/\/github\.com\//)
  assert.equal(
    sources[3].baseUrl,
    'https://github.com/gyhgyhgyhgyh92/DevPrompt-AI/releases/download/updates/',
  )
})

test('buildSourceList：开发覆盖只保留一个源并补齐斜杠', () => {
  assert.deepEqual(buildSourceList('http://127.0.0.1:9000'), [
    { id: 'dev', baseUrl: 'http://127.0.0.1:9000/' },
  ])
  assert.deepEqual(buildSourceList('http://127.0.0.1:9000/'), [
    { id: 'dev', baseUrl: 'http://127.0.0.1:9000/' },
  ])
})

test('isAllowedUpdateHost：放行镜像与 GitHub 资产域名', () => {
  assert.equal(isAllowedUpdateHost('https://ghfast.top/https://github.com/a/b'), true)
  assert.equal(isAllowedUpdateHost('https://ghproxy.net/x'), true)
  assert.equal(isAllowedUpdateHost('https://gh-proxy.com/x'), true)
  assert.equal(isAllowedUpdateHost('https://github.com/a/b/releases/download/x.exe'), true)
  assert.equal(isAllowedUpdateHost('https://objects.githubusercontent.com/x'), true)
  assert.equal(isAllowedUpdateHost('https://release-assets.githubusercontent.com/x'), true)
})

test('isAllowedUpdateHost：拒绝陌生域名、伪装域名与明文 HTTP', () => {
  assert.equal(isAllowedUpdateHost('https://evil.example/x.exe'), false)
  assert.equal(isAllowedUpdateHost('https://ghfast.top.evil.example/x.exe'), false)
  assert.equal(isAllowedUpdateHost('http://ghfast.top/x.exe'), false)
  assert.equal(isAllowedUpdateHost('not a url'), false)
})

test('isAllowedUpdateHost：loopback 仅在显式放行时可用', () => {
  assert.equal(isAllowedUpdateHost('http://127.0.0.1:9000/x.exe'), false)
  assert.equal(isAllowedUpdateHost('http://127.0.0.1:9000/x.exe', true), true)
  assert.equal(isAllowedUpdateHost('http://localhost:9000/x.exe', true), true)
})

test('manifestFingerprint：提取版本与全部 sha512', () => {
  const fingerprint = manifestFingerprint(MANIFEST)
  assert.match(fingerprint, /^0\.3\.0\|/)
  assert.match(fingerprint, /abc\+\/def==/)
})

test('sameManifest：同一份清单、CRLF 与尾部空白不影响', () => {
  assert.equal(sameManifest(MANIFEST, MANIFEST), true)
  assert.equal(sameManifest(MANIFEST, `\r\n${MANIFEST.replace(/\n/g, '\r\n')}\r\n`), true)
})

test('sameManifest：版本或 sha512 不同即拒绝', () => {
  assert.equal(sameManifest(MANIFEST, MANIFEST.replace('0.3.0', '0.3.1')), false)
  assert.equal(sameManifest(MANIFEST, MANIFEST.replace('abc+/def==', 'zzz==')), false)
})

test('sameManifest：缺字段的清单不可信', () => {
  assert.equal(sameManifest(MANIFEST, 'version: 0.3.0\nfiles:\n  - url: x.exe\n'), false)
  assert.equal(manifestFingerprint('files:\n  - url: x.exe\n'), '')
})

test('formatBytes：MB 展示', () => {
  assert.equal(formatBytes(undefined), '')
  assert.equal(formatBytes(0), '')
  assert.equal(formatBytes(153597724), '146 MB')
  assert.equal(formatBytes(5 * 1024 * 1024), '5.0 MB')
})
