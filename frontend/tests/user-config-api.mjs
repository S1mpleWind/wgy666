import assert from 'node:assert/strict'

assert.equal(process.env.TEST_ALLOW_CONFIG_MUTATION, '1', 'run through npm run test:user-config')
const apiBase = process.env.TEST_API_BASE_URL
assert.ok(apiBase, 'TEST_API_BASE_URL is required')
const endpoint = `${apiBase}/api/users/config`

async function jsonResponse(response) {
  const body = await response.json()
  assert.equal(response.ok, true, JSON.stringify(body))
  return body
}

const initial = await jsonResponse(await fetch(endpoint))
assert.equal(typeof initial.llm_api_base_url, 'string')
assert.equal(typeof initial.llm_model, 'string')
assert.equal(typeof initial.llm_api_key_configured, 'boolean')
assert.equal('llm_api_key' in initial, false)
assert.equal('github_token' in initial, false)
assert.equal('github_webhook_secret' in initial, false)

const unique = Date.now()
const secrets = {
  llm: `e2e-llm-${unique}`,
  github: `e2e-github-${unique}`,
  webhook: `e2e-webhook-${unique}`,
}
const updatedResponse = await fetch(endpoint, {
  method: 'PATCH',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    llm_api_base_url: 'https://e2e.example.com/v1',
    llm_model: 'e2e-model',
    llm_api_key: secrets.llm,
    github_token: secrets.github,
    github_webhook_secret: secrets.webhook,
  }),
})
const updatedText = await updatedResponse.text()
assert.equal(updatedResponse.ok, true, updatedText)
for (const secret of Object.values(secrets)) assert.equal(updatedText.includes(secret), false)

const updated = JSON.parse(updatedText)
assert.equal(updated.llm_api_base_url, 'https://e2e.example.com/v1')
assert.equal(updated.llm_model, 'e2e-model')
assert.equal(updated.llm_api_key_configured, true)
assert.equal(updated.github_token_configured, true)
assert.equal(updated.github_webhook_secret_configured, true)

const cleared = await jsonResponse(await fetch(endpoint, {
  method: 'PATCH',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    clear_llm_api_key: true,
    clear_github_token: true,
    clear_github_webhook_secret: true,
  }),
}))
assert.equal(cleared.llm_api_key_configured, false)
assert.equal(cleared.github_token_configured, false)
assert.equal(cleared.github_webhook_secret_configured, false)

console.log('user config frontend/backend HTTP contract: passed')
