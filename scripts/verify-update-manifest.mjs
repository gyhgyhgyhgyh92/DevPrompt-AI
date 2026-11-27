#!/usr/bin/env node
/**
 * 校验 electron-builder 生成的 latest.yml 与实际安装包一致。
 *
 * 用法：
 *   node scripts/verify-update-manifest.mjs <latest.yml> [exe...]
 *
 * 不传 exe 时校验清单里列出的全部 .exe；传了就校验指定文件必须在清单中且哈希匹配。
 * 发布 CI 在创建 release / 更新 updates 指针之前各跑一次，避免把坏清单发出去。
 */

import { createHash } from 'node:crypto'
import { readFileSync, statSync } from 'node:fs'
import { basename, dirname, resolve } from 'node:path'

function parseManifest(text) {
  const version = /^version:\s*['"]?([^'"\r\n]+?)['"]?\s*$/m.exec(text)?.[1]?.trim() ?? ''
  const files = []
  let current = null
  for (const line of text.split(/\r?\n/)) {
    const url = /^\s*-\s*url:\s*(.+?)\s*$/.exec(line)
    if (url !== null) {
      current = { url: url[1].replace(/^['"]|['"]$/g, ''), sha512: '', size: undefined }
      files.push(current)
      continue
    }
    if (current === null) continue
    const sha = /^\s{2,}sha512:\s*['"]?([^'"\r\n]+?)['"]?\s*$/.exec(line)
    if (sha !== null) {
      current.sha512 = sha[1].trim()
      continue
    }
    const size = /^\s{2,}size:\s*(\d+)\s*$/.exec(line)
    if (size !== null) current.size = Number(size[1])
  }

  if (files.length === 0) {
    const url = /^path:\s*(.+?)\s*$/m.exec(text)?.[1]?.replace(/^['"]|['"]$/g, '')
    const sha = /^sha512:\s*['"]?([^'"\r\n]+?)['"]?\s*$/m.exec(text)?.[1]?.trim()
    if (url && sha) files.push({ url, sha512: sha, size: undefined })
  }
  return { version, files }
}

function fail(message) {
  console.error(`[verify-update-manifest] ${message}`)
  process.exit(1)
}

const [manifestPath, ...explicitExes] = process.argv.slice(2)
if (!manifestPath) {
  fail('用法：node scripts/verify-update-manifest.mjs <latest.yml> [exe...]')
}

const manifestAbs = resolve(manifestPath)
const manifestText = readFileSync(manifestAbs, 'utf8')
const { version, files } = parseManifest(manifestText)

if (!/^\d+\.\d+\.\d+/.test(version)) fail(`清单缺少合法 version：${JSON.stringify(version)}`)
if (files.length === 0) fail('清单没有可校验的 files/path 条目')

const dir = dirname(manifestAbs)
const byName = new Map(files.map((file) => [basename(file.url), file]))
const targets =
  explicitExes.length > 0 ? explicitExes : files.map((file) => resolve(dir, file.url))

let checked = 0
for (const target of targets) {
  const abs = resolve(target)
  const name = basename(abs)
  const entry = byName.get(name)
  if (entry === undefined) fail(`文件不在清单中：${name}`)

  let info
  try {
    info = statSync(abs)
  } catch {
    fail(`清单引用的文件不存在：${abs}`)
  }
  if (entry.size !== undefined && entry.size !== info.size) {
    fail(`大小不一致：${name} 清单=${entry.size} 实际=${info.size}`)
  }
  if (entry.sha512 === '') fail(`清单缺少 sha512：${name}`)

  const digest = createHash('sha512').update(readFileSync(abs)).digest('base64')
  if (digest !== entry.sha512) {
    fail(`SHA512 不一致：${name}\n  清单=${entry.sha512}\n  实际=${digest}`)
  }
  console.log(
    `[verify-update-manifest] OK ${name} (${info.size} bytes, sha512 匹配, version=${version})`,
  )
  checked += 1
}

if (checked === 0) fail('没有校验任何文件')
