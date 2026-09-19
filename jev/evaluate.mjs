import { experimental_evaluate as evaluate } from 'ai';
import { pathToFileURL } from 'node:url';

export function safeError(error) {
  const code = Number.isInteger(error.statusCode) ? `http_${error.statusCode}` : 'evaluation_failed';
  const value = error.cause?.responseHeaders?.['retry-after'];
  const seconds = value && /^\d+$/.test(value) ? Number(value) : (Date.parse(value) - Date.now()) / 1000;
  return {error: code, retry_after: Number.isFinite(seconds) && seconds >= 0 ? Math.ceil(seconds) : 900};
}

export async function run(payload, model = 'typesafe-ai/jev') {
  const result = await evaluate({
    model, state: payload.state, questions: payload.questions,
    maxRetries: 0, abortSignal: AbortSignal.timeout(20000),
  });
  // Never expose raw provider responses, request headers or error bodies.
  return {
    answers: result.answers, usage: result.usage ?? {},
    rounding: result.rounding ?? {},
    response_id: result.providerMetadata?.gateway?.generationId ?? result.response?.id ?? null,
    served_model: result.response?.modelId ?? null,
    sdk: 'ai@7.0.106',
  };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    let input = '';
    for await (const chunk of process.stdin) {
      input += chunk;
      if (input.length > 16000) throw new Error('input_limit');
    }
    if (!process.env.AI_GATEWAY_API_KEY) throw new Error('missing_key');
    process.stdout.write(JSON.stringify(await run(JSON.parse(input))));
  } catch (error) {
    process.stdout.write(JSON.stringify(safeError(error)));
    process.exitCode = 1;
  }
}
