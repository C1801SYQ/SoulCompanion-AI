import { CommunityError, type ContentStatus } from './apiTypes';
import { CloudError } from '../cloud/types';

export const CONTENT_STATUS_LABELS: Record<ContentStatus, string> = {
  pending: '待审核', published: '已公开', rejected: '未通过审核', hidden: '已隐藏', deleted: '已撤回',
};

/** Error text is selected locally; server payloads and identity details never enter the UI. */
export function communityFailureText(error: unknown): string {
  if (error instanceof CommunityError) {
    if (error.serverCode === 'parent_profile_required') return '请先主动设置公开社区昵称，再提交内容。';
    if (error.status === 401) return '登录已失效，请重新登录后再操作。';
    if (error.status === 403) return '当前账号不能执行这项操作。';
    if (error.status === 404) return '内容已不可查看，请刷新后继续。';
    if (error.status === 409) return '内容或资料已经变化。请重新读取当前状态，核对后再操作。';
    if (error.status === 413 || error.status === 422) return '文字或选择不符合要求，请检查长度、纯文本和标签。';
    if (error.status === 429) return '操作较频繁，请稍后再试。';
    if (error.status === 503) return '服务暂时不可用。写入结果可能尚未确认，请核对本人内容或使用原操作安全重试。';
    return error.message;
  }
  if (error instanceof CloudError) return error.message;
  return '暂时无法完成，请检查连接后再试。';
}

export function isUncertainWrite(error: unknown): boolean {
  return error instanceof CommunityError && (error.status === 503 || error.kind === 'offline');
}

export function isCancelled(error: unknown): boolean {
  return (error instanceof CommunityError || error instanceof CloudError) && error.kind === 'cancelled';
}

export function isUnavailable(error: unknown): boolean {
  return error instanceof CommunityError && error.status === 404;
}

export function confirmedPostText(status: ContentStatus): string {
  return ({ pending: '已提交审核，暂时不会公开展示。', published: '云端确认这条投稿当前已公开。',
    rejected: '云端确认这条投稿未通过审核。可在我的投稿查看反馈。',
    hidden: '云端确认这条投稿当前已隐藏。可在我的投稿查看反馈。', deleted: '云端确认这条投稿已撤回。' })[status];
}

export function publicTime(value: string): string {
  return `${value.slice(0, 19).replace('T', ' ')} UTC`;
}

export function textSummary(value: string): string {
  const characters = Array.from(value);
  return characters.length > 120 ? `${characters.slice(0, 120).join('')}…` : value;
}
