import type { CloudApi } from './types';
import { CloudApiTransport } from './transport';
import * as parse from './validation';
export function createCloudApi(transport: CloudApiTransport): CloudApi {
  const query = (child: string) => `?child_profile_id=${encodeURIComponent(parse.cloudId(child))}&limit=100&offset=0`;
  return {
    me: () => transport.request('GET', '/api/v2/me', parse.user),
    updateMe: display_name => transport.request('PATCH', '/api/v2/me', parse.user, { display_name: parse.nickname(display_name) }),
    children: () => transport.request('GET', '/api/v2/children?limit=100&offset=0', parse.page(parse.child)),
    createChild: nickname => transport.request('POST', '/api/v2/children', parse.child, { nickname: parse.nickname(nickname) }),
    child: id => transport.request('GET', `/api/v2/children/${parse.cloudId(id)}`, parse.child),
    updateChild: (id, nickname) => transport.request('PATCH', `/api/v2/children/${parse.cloudId(id)}`, parse.child, { nickname: parse.nickname(nickname) }),
    archiveChild: id => transport.request('DELETE', `/api/v2/children/${parse.cloudId(id)}`, () => undefined, undefined, true),
    createSession: (child_profile_id, source_platform) => transport.request('POST', '/api/v2/sessions', parse.session, { child_profile_id: parse.cloudId(child_profile_id), source_platform }),
    endSession: id => transport.request('POST', `/api/v2/sessions/${parse.cloudId(id)}/end`, parse.session),
    sessions: id => transport.request('GET', `/api/v2/sessions${query(id)}`, parse.page(parse.session)),
    emotions: id => transport.request('GET', `/api/v2/emotions${query(id)}`, parse.page(parse.emotion)),
    reports: id => transport.request('GET', `/api/v2/reports${query(id)}`, parse.page(parse.report)),
    currentReport: id => transport.request('GET', `/api/v2/reports/current${query(id).split('&')[0]}`, parse.currentReport),
  };
}
