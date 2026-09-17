import { generateText } from 'ai';
import { config } from 'dotenv';

config({ path: '.env.local' });

async function main() {
  const result = await generateText({
    model: 'openai/gpt-5.5',
    prompt: 'Invent a new holiday and describe its traditions.',
  });

  console.log(result.text);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
