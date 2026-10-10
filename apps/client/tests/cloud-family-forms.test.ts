import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactElement, ReactNode } from 'react';
import type { CloudState } from '../src/cloud/store';

const mock = vi.hoisted(() => ({ state: undefined as unknown as CloudState, store: { updateParentProfile: vi.fn(), createProfile: vi.fn(), updateProfile: vi.fn(), updateUser: vi.fn(), getState: vi.fn(), selectProfile: vi.fn(), signIn: vi.fn(), signOut: vi.fn(), refresh: vi.fn() }, stop: vi.fn(), dismissKeyboard: vi.fn(), slots: [] as unknown[], cursor: 0, effects: [] as Array<() => void> }));
/** A hook/event harness: the same JSX handlers execute without devices, DOM or network. */
vi.mock('react', async () => {
  const real = await vi.importActual<typeof import('react')>('react');
  return { ...real,
    useState: (initial: unknown) => { const index = mock.cursor++; if (!(index in mock.slots)) mock.slots[index] = typeof initial === 'function' ? initial() : initial; return [mock.slots[index], (value: unknown) => { mock.slots[index] = typeof value === 'function' ? value(mock.slots[index]) : value; }]; },
    useRef: (initial: unknown) => { const index = mock.cursor++; if (!(index in mock.slots)) mock.slots[index] = { current: initial }; return mock.slots[index]; },
    useEffect: (effect: () => void, dependencies: unknown[]) => { const index = mock.cursor++; const old = mock.slots[index] as unknown[] | undefined; if (!old || dependencies.some((value, i) => value !== old[i])) { mock.slots[index] = dependencies; mock.effects.push(effect); } },
  };
});
vi.mock('@tarojs/components', () => ({ Input: 'input', Text: 'span', View: 'div' }));
vi.mock('../src/components/AccessibleButton', () => ({ AccessibleButton: 'button' }));
vi.mock('../src/components/Primitives', () => ({ EmptyState: 'empty-state', SectionCard: 'section', StatusPill: 'status-pill' }));
vi.mock('../src/state/CloudProvider', () => ({ useCloud: () => ({ state: mock.state, store: mock.store }) }));
vi.mock('../src/state/SessionProvider', () => ({ useSession: () => ({ stop: mock.stop }) }));
vi.mock('../src/cloud/auth/platform', () => ({ cloudSourcePlatform: 'web' }));
vi.mock('../src/platform/keyboard', () => ({ textInputKeyboardProps: {}, dismissKeyboard: mock.dismissKeyboard }));
import { CloudAccount } from '../src/components/CloudAccount';
import { ParentCommunityIdentity } from '../src/components/ParentCommunityIdentity';

function render(component: () => ReactElement, runEffects = true): ReactElement {
  mock.cursor = 0; mock.effects = []; const tree = component();
  if (runEffects) for (const effect of mock.effects) effect(); return tree;
}
type Node = ReactElement<{ id?: string; value?: string; disabled?: boolean; children?: ReactNode; onInput?: (event: { detail: { value: string } }) => void; onClick?: () => void }>;
function find(node: ReactNode, id: string): Node | null {
  if (Array.isArray(node)) { for (const child of node) { const result = find(child, id); if (result) return result; } return null; }
  if (!node || typeof node !== 'object' || !('props' in node)) return null;
  const value = node as Node; return value.props.id === id ? value : find(value.props.children, id);
}
function input(tree: ReactNode, id: string, value: string) { const control = find(tree, id); expect(control).not.toBeNull(); control!.props.onInput!({ detail: { value } }); }
const tick = async () => { for (let index = 0; index < 30; index++) await Promise.resolve(); };
function deferred() { let resolve!: (value: boolean) => void; const promise = new Promise<boolean>(done => { resolve = done; }); return { promise, resolve }; }
const id = '11111111-1111-4111-8111-111111111111';
beforeEach(() => {
  vi.clearAllMocks(); mock.slots = []; mock.cursor = 0; mock.effects = [];
  mock.state = { enabled: true, auth: { status: 'signed_in', principal: { subject: 'synthetic-parent', provider: 'fake' }, epoch: 1, message: '' }, epoch: 1, status: 'ready', message: '',
    user: { id, display_name: '私有账户名', status: 'active', created_at: '', updated_at: '' }, profiles: [{ id, nickname: '私有儿童名', age_band: '6-8', status: 'active', created_at: '', updated_at: '' }], selectedId: null,
    sessions: [], emotions: [], reports: [], capabilities: { child_age_band: true, parent_profile: true }, parentProfileStatus: 'ready', parentProfile: { id, nickname: '合成公开昵称', created_at: '', updated_at: '' } };
  mock.store.getState.mockImplementation(() => mock.state); mock.dismissKeyboard.mockResolvedValue(undefined);
});
describe('PC02 settings form boundaries and confirmed saves', () => {
  it('the first new-account render hides a public draft and status before effects run', async () => {
    render(ParentCommunityIdentity); let old = render(ParentCommunityIdentity); input(old, 'cloud-parent-nickname', '旧合成家长草稿'); old = render(ParentCommunityIdentity);
    mock.store.updateParentProfile.mockResolvedValue(false); find(old, 'cloud-parent-save')!.props.onClick!(); await tick(); render(ParentCommunityIdentity);
    mock.state = { ...mock.state, auth: { ...mock.state.auth, epoch: 2 } };
    const first = render(ParentCommunityIdentity, false);
    expect(find(first, 'cloud-parent-nickname')!.props.value).toBe(''); expect(find(first, 'cloud-parent-save')!.props.disabled).toBe(true);
    expect(find(first, 'cloud-parent-save-status')).toBeNull();
  });
  it('a stale public save or input event after account switch cannot submit or seed old text', async () => {
    render(ParentCommunityIdentity); let old = render(ParentCommunityIdentity); input(old, 'cloud-parent-nickname', '旧合成公开草稿'); old = render(ParentCommunityIdentity);
    mock.state = { ...mock.state, auth: { ...mock.state.auth, epoch: 2 } };
    find(old, 'cloud-parent-save')!.props.onClick!(); input(old, 'cloud-parent-nickname', '迟到旧事件'); await tick();
    expect(mock.store.updateParentProfile).not.toHaveBeenCalled();
    const first = render(ParentCommunityIdentity, false); expect(find(first, 'cloud-parent-nickname')!.props.value).toBe('');
  });
  it('the first new-account render synchronously hides private name, child edit and age', () => {
    render(CloudAccount); let old = render(CloudAccount); input(old, 'cloud-display-name-input', '旧私有账户草稿'); find(old, 'cloud-profile-edit-0')!.props.onClick!(); old = render(CloudAccount);
    mock.state = { ...mock.state, auth: { ...mock.state.auth, epoch: 2 } };
    const first = render(CloudAccount, false);
    expect(find(first, 'cloud-display-name-input')!.props.value).toBe(''); expect(find(first, 'cloud-profile-nickname')!.props.value).toBe('');
    expect(find(first, 'cloud-profile-save')!.props.children).toBe('创建档案'); expect(find(first, 'cloud-profile-save')!.props.disabled).toBe(true);
    expect((find(first, 'cloud-profile-age-none')!.props as Record<string, unknown>)['aria-pressed']).toBe(true);
  });
  it('stale private edit/input/save events cannot send or show old fields under a new account', async () => {
    render(CloudAccount); let old = render(CloudAccount); input(old, 'cloud-display-name-input', '旧账户草稿'); input(old, 'cloud-profile-nickname', '旧孩子草稿'); old = render(CloudAccount);
    mock.state = { ...mock.state, auth: { ...mock.state.auth, epoch: 2 } };
    find(old, 'cloud-save-name')!.props.onClick!(); find(old, 'cloud-profile-save')!.props.onClick!(); find(old, 'cloud-profile-edit-0')!.props.onClick!(); input(old, 'cloud-profile-nickname', '迟到私有事件'); await tick();
    expect(mock.store.updateUser).not.toHaveBeenCalled(); expect(mock.store.createProfile).not.toHaveBeenCalled(); expect(mock.store.updateProfile).not.toHaveBeenCalled();
    const first = render(CloudAccount, false); expect(find(first, 'cloud-display-name-input')!.props.value).toBe(''); expect(find(first, 'cloud-profile-nickname')!.props.value).toBe('');
  });
  it('private drafts cannot return when selection goes A to B to A before effects', () => {
    mock.state = { ...mock.state, selectedId: id }; render(CloudAccount); let old = render(CloudAccount); find(old, 'cloud-profile-edit-0')!.props.onClick!(); old = render(CloudAccount);
    mock.state = { ...mock.state, selectedId: '22222222-2222-4222-8222-222222222222' }; let first = render(CloudAccount, false);
    expect(find(first, 'cloud-profile-nickname')!.props.value).toBe('');
    mock.state = { ...mock.state, selectedId: id }; first = render(CloudAccount, false);
    expect(find(first, 'cloud-profile-nickname')!.props.value).toBe('');
    find(old, 'cloud-profile-save')!.props.onClick!(); expect(mock.store.updateProfile).not.toHaveBeenCalled();
  });
  it('a stale login event cannot reuse old username and password after auth changes', () => {
    mock.state = { ...mock.state, auth: { ...mock.state.auth, status: 'signed_out' } }; render(CloudAccount); let old = render(CloudAccount);
    input(old, 'cloud-username', 'synthetic-old-login'); input(old, 'cloud-password', 'synthetic-old-password'); old = render(CloudAccount);
    mock.state = { ...mock.state, auth: { ...mock.state.auth, epoch: 2 } }; find(old, 'cloud-sign-in')!.props.onClick!();
    expect(mock.store.signIn).not.toHaveBeenCalled(); const first = render(CloudAccount, false);
    expect(find(first, 'cloud-username')!.props.value).toBe(''); expect(find(first, 'cloud-password')!.props.value).toBe('');
  });
  it('a previous private save completion cannot clear a new account draft before effects', async () => {
    render(CloudAccount); let old = render(CloudAccount); input(old, 'cloud-display-name-input', '旧私有保存稿'); old = render(CloudAccount);
    const pending = deferred(); mock.store.updateUser.mockReturnValue(pending.promise); find(old, 'cloud-save-name')!.props.onClick!();
    mock.state = { ...mock.state, auth: { ...mock.state.auth, epoch: 2 } };
    let first = render(CloudAccount, false); input(first, 'cloud-display-name-input', '新账户输入稿');
    pending.resolve(true); await tick(); first = render(CloudAccount, false);
    expect(find(first, 'cloud-display-name-input')!.props.value).toBe('新账户输入稿');
  });
  it('queued old-scope and new-scope cleanup effects cannot clear a newly owned draft', () => {
    let old = render(ParentCommunityIdentity, false); const oldEffects = [...mock.effects]; input(old, 'cloud-parent-nickname', '旧公开输入稿');
    mock.state = { ...mock.state, auth: { ...mock.state.auth, epoch: 2 } };
    let first = render(ParentCommunityIdentity, false); const newEffects = [...mock.effects]; input(first, 'cloud-parent-nickname', '新公开输入稿');
    for (const effect of [...oldEffects, ...newEffects]) effect(); first = render(ParentCommunityIdentity, false);
    expect(find(first, 'cloud-parent-nickname')!.props.value).toBe('新公开输入稿');
  });
  it.each(['idle', 'loading', 'error'] as const)('unconfirmed parent status %s never claims no nickname or offers save', parentProfileStatus => {
    mock.state = { ...mock.state, status: 'ready', parentProfile: null, parentProfileStatus };
    render(ParentCommunityIdentity); const tree = render(ParentCommunityIdentity);
    expect(find(tree, 'cloud-parent-saved-name')).toBeNull(); expect(find(tree, 'cloud-parent-save')).toBeNull();
    expect(find(tree, 'cloud-parent-nickname')).toBeNull(); expect(mock.store.updateParentProfile).not.toHaveBeenCalled();
    if (parentProfileStatus === 'error') { find(tree, 'cloud-parent-retry')!.props.onClick!(); expect(mock.store.refresh).toHaveBeenCalledOnce(); }
  });
  it('only a successful null response displays unset and permits valid input to save', () => {
    mock.state = { ...mock.state, parentProfile: null, parentProfileStatus: 'ready' };
    render(ParentCommunityIdentity); let tree = render(ParentCommunityIdentity);
    expect(find(tree, 'cloud-parent-saved-name')!.props.children).toBe('尚未设置公开社区昵称');
    input(tree, 'cloud-parent-nickname', '主动合成昵称'); tree = render(ParentCommunityIdentity);
    expect(find(tree, 'cloud-parent-save')!.props.disabled).toBe(false);
  });
  it('public nickname input never prefills private user, child or saved nickname', () => {
    render(ParentCommunityIdentity); const tree = render(ParentCommunityIdentity);
    expect(find(tree, 'cloud-parent-nickname')!.props.value).toBe('');
    expect(find(tree, 'cloud-parent-save')!.props.disabled).toBe(true);
    expect(find(tree, 'cloud-parent-saved-name')!.props.children).toBe('已保存昵称：合成公开昵称');
    expect(mock.store.updateParentProfile).not.toHaveBeenCalled();
  });
  it('failed nickname save preserves input and explicitly remains unconfirmed', async () => {
    render(ParentCommunityIdentity); let tree = render(ParentCommunityIdentity); input(tree, 'cloud-parent-nickname', '新的合成昵称'); tree = render(ParentCommunityIdentity);
    mock.store.updateParentProfile.mockResolvedValue(false); find(tree, 'cloud-parent-save')!.props.onClick!(); await tick(); tree = render(ParentCommunityIdentity);
    expect(find(tree, 'cloud-parent-nickname')!.props.value).toBe('新的合成昵称');
    expect(find(tree, 'cloud-parent-save-status')).not.toBeNull();
    expect(mock.store.updateParentProfile).toHaveBeenCalledWith('新的合成昵称');
  });
  it('invalid or unavailable public nickname cannot submit any real write', () => {
    render(ParentCommunityIdentity); let tree = render(ParentCommunityIdentity); input(tree, 'cloud-parent-nickname', '<script>'); tree = render(ParentCommunityIdentity);
    expect(find(tree, 'cloud-parent-save')!.props.disabled).toBe(true); find(tree, 'cloud-parent-save')!.props.onClick!(); expect(mock.store.updateParentProfile).not.toHaveBeenCalled();
    mock.state = { ...mock.state, capabilities: { child_age_band: false, parent_profile: false } }; tree = render(ParentCommunityIdentity);
    expect(find(tree, 'cloud-parent-nickname')).toBeNull(); expect(find(tree, 'cloud-parent-save')).toBeNull();
  });
  it('late old-account save does not clear the new account draft or claim success', async () => {
    render(ParentCommunityIdentity); let tree = render(ParentCommunityIdentity); input(tree, 'cloud-parent-nickname', '第一合成家长'); tree = render(ParentCommunityIdentity);
    const old = deferred(); mock.store.updateParentProfile.mockReturnValue(old.promise); find(tree, 'cloud-parent-save')!.props.onClick!();
    mock.state = { ...mock.state, auth: { ...mock.state.auth, epoch: 2 } }; render(ParentCommunityIdentity); tree = render(ParentCommunityIdentity);
    input(tree, 'cloud-parent-nickname', '第二合成家长'); old.resolve(true); await tick(); tree = render(ParentCommunityIdentity);
    expect(find(tree, 'cloud-parent-nickname')!.props.value).toBe('第二合成家长'); expect(find(tree, 'cloud-parent-save-status')).toBeNull();
  });
  it('failed private child save keeps both nickname and optional age', async () => {
    render(CloudAccount); let tree = render(CloudAccount); input(tree, 'cloud-profile-nickname', '合成孩子'); tree = render(CloudAccount);
    find(tree, 'cloud-profile-age-9-12')!.props.onClick!(); tree = render(CloudAccount);
    mock.store.createProfile.mockResolvedValue(false); find(tree, 'cloud-profile-save')!.props.onClick!(); await tick(); tree = render(CloudAccount);
    expect(find(tree, 'cloud-profile-nickname')!.props.value).toBe('合成孩子'); expect(mock.store.createProfile).toHaveBeenCalledWith('合成孩子', '9-12');
  });
  it('old server disables every age button while preserving nickname-only edits', async () => {
    mock.state = { ...mock.state, capabilities: { child_age_band: false, parent_profile: false } };
    render(CloudAccount); let tree = render(CloudAccount);
    for (const age of ['none', '0-2', '3-5', '6-8', '9-12', '13-15', '16-18']) expect(find(tree, `cloud-profile-age-${age}`)!.props.disabled).toBe(true);
    input(tree, 'cloud-profile-nickname', '合成孩子'); tree = render(CloudAccount); mock.store.createProfile.mockResolvedValue(true);
    expect(find(tree, 'cloud-profile-save')!.props.disabled).toBe(false); find(tree, 'cloud-profile-save')!.props.onClick!(); await tick();
    expect(mock.store.createProfile).toHaveBeenCalledWith('合成孩子', undefined);
  });
  it('editing a child starts with its own age and can explicitly clear it', async () => {
    render(CloudAccount); let tree = render(CloudAccount); find(tree, 'cloud-profile-edit-0')!.props.onClick!(); tree = render(CloudAccount);
    expect(find(tree, 'cloud-profile-nickname')!.props.value).toBe('私有儿童名');
    find(tree, 'cloud-profile-age-none')!.props.onClick!(); tree = render(CloudAccount); mock.store.updateProfile.mockResolvedValue(true);
    find(tree, 'cloud-profile-save')!.props.onClick!(); await tick();
    expect(mock.store.updateProfile).toHaveBeenCalledWith(id, '私有儿童名', null); expect(mock.store.updateParentProfile).not.toHaveBeenCalled();
  });
  it('failed private account rename retains typed text', async () => {
    render(CloudAccount); let tree = render(CloudAccount); input(tree, 'cloud-display-name-input', '新的私有名字'); tree = render(CloudAccount);
    mock.store.updateUser.mockResolvedValue(false); find(tree, 'cloud-save-name')!.props.onClick!(); await tick(); tree = render(CloudAccount);
    expect(find(tree, 'cloud-display-name-input')!.props.value).toBe('新的私有名字'); expect(mock.store.updateParentProfile).not.toHaveBeenCalled();
  });
});
