import { test } from 'node:test';
import assert from 'node:assert/strict';
import { run } from './evaluate.mjs';

const model = {
  specificationVersion:'v4', provider:'fixture', modelId:'jev-test',
  supportedQuestionTypes:['boolean','choice'],
  async doEvaluate(options) {
    assert.equal(options.state.headline,'Untrusted headline');
    return {answers:{relevant:{type:'boolean',probability:.7}},
      usage:{inputTokens:20,outputTokens:3},warnings:[],
      response:{id:'fixture-id',headers:{authorization:'DO-NOT-EXPORT'},body:'DO-NOT-EXPORT'}};
  },
};
test('real SDK evaluation contract, usage and output sanitization', async () => {
  const result = await run({state:{headline:'Untrusted headline'},questions:{relevant:{type:'boolean',instructions:'Relevant?'}}},model);
  assert.equal(result.answers.relevant.probability,.7);
  assert.equal(result.usage.inputTokens,20);
  assert.equal(JSON.stringify(result).includes('DO-NOT-EXPORT'),false);
});
test('the SDK rejects incomplete provider answers', async () => {
  await assert.rejects(run({state:{},questions:{missing:{type:'boolean',instructions:'A question'}}},
    {...model,async doEvaluate(){return {answers:{},warnings:[]};}}));
});

test('rate-limit metadata preserves Retry-After without exporting secrets', async () => {
  const {safeError} = await import('./evaluate.mjs');
  const e = {statusCode:429,message:'SECRET',cause:{responseHeaders:{'retry-after':'3600',authorization:'SECRET'}}};
  assert.deepEqual(safeError(e),{error:'http_429',retry_after:3600});
  assert.equal(safeError({statusCode:429}).retry_after,900);
});
