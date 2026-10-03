import Taro from '@tarojs/taro';

/** Export only after an explicit user action; reports and object URLs stay temporary. */
export async function exportMarkdown(text: string, filename: string): Promise<'downloaded' | 'copied'> {
  if (!/^[a-zA-Z0-9_-]{1,100}\.md$/.test(filename)) throw new Error('报告文件名无效');
  if (Taro.getEnv() !== Taro.ENV_TYPE.WEB) {
    await Taro.setClipboardData({ data: text });
    return 'copied';
  }
  const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  try {
    link.click();
  } finally {
    link.remove();
    // Allow the browser to begin consuming the Blob before releasing it.
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return 'downloaded';
}
