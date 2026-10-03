import { Text, View } from '@tarojs/components';
import { AccessibleButton as Button } from '../../components/AccessibleButton';
import { AppShell, PageHeader } from '../../components/AppShell';
import { withClientErrorBoundary } from '../../components/ClientErrorBoundary';
import { componentLabel, componentStateLabels, visibleComponentNames } from '../../components/format';
import { ResourceNotice, SectionCard, StatusPill } from '../../components/Primitives';
import { useResource } from '../../hooks/useResource';
import { useCompanion } from '../../state/AppProvider';

function SettingsPage() {
  const { api, source, setSource, motionEnabled, setMotionEnabled, demoOnly } = useCompanion();
  const settings = useResource(`settings:${source}`, () => api.getSettings());
  const system = useResource(`settings:system:${source}`, () => api.getSystem(), 10000);
  const database = system.status === 'ready' ? system.data?.components.database.status : undefined;
  const components = system.status === 'ready' ? system.data?.components : null;
  return <AppShell page="settings">
    <PageHeader eyebrow="SETTINGS · 设置" title="以你的节奏，安心陪伴。" description="了解数据从哪里来，选择舒服的体验方式。" />
    <View className="sc-profile"><View className="sc-profile-avatar" ariaHidden><View /></View><View><Text className="sc-profile-title">欢迎来到你的陪伴空间</Text><Text className="sc-body-muted">访客体验 · 账号服务尚未启用</Text></View><StatusPill>V2 体验预览</StatusPill></View>
    <View className="sc-settings-grid">
      <View className="sc-settings-column">
        <SectionCard title="数据来源" eyebrow="你可以随时选择">
          <View className="sc-mode-options"><Button id="mode-real" className={`sc-mode-option ${source === 'real' ? 'sc-mode-option--selected' : ''}`} aria-pressed={source === 'real'} disabled={demoOnly} onClick={() => setSource('real')}><View className="sc-mode-option-heading"><Text>REAL · 真实数据</Text><Text className="sc-mode-check">{source === 'real' ? '已选择' : demoOnly ? '此构建不可用' : '选择'}</Text></View><Text className="sc-body-muted">读取配置的本机服务，未连接时显示离线。</Text></Button><Button id="mode-demo" className={`sc-mode-option ${source === 'demo' ? 'sc-mode-option--selected' : ''}`} aria-pressed={source === 'demo'} onClick={() => setSource('demo')}><View className="sc-mode-option-heading"><Text>DEMO · 合成示例</Text><Text className="sc-mode-check">{source === 'demo' ? '已选择' : '选择'}</Text></View><Text className="sc-body-muted">体验界面与报告，不向真实服务发送请求。</Text></Button></View>
          <Text className="sc-setting-footnote">切换演示仅改变当前客户端的数据来源，不会停止另外运行的旧设备服务。当前客户端不会采集音视频。</Text>
        </SectionCard>
        <SectionCard title="让体验更舒适" eyebrow="动画与动态效果">
          <View className="sc-setting-row"><View><Text className="sc-setting-name">Emotion Orb 呼吸动画</Text><Text className="sc-body-muted">轻柔变化，始终尊重系统的减少动态效果设置。</Text></View><Button id="motion-toggle" className={`sc-toggle ${motionEnabled ? 'sc-toggle--on' : ''}`} role="switch" aria-checked={motionEnabled} ariaLabel={`Emotion Orb 动画，${motionEnabled ? '开启' : '关闭'}`} onClick={() => setMotionEnabled(!motionEnabled)}><View className="sc-toggle-knob" /><Text>{motionEnabled ? '开启' : '关闭'}</Text></Button></View>
        </SectionCard>
        <SectionCard title="隐私与自主选择" eyebrow="知道发生了什么">
          <View className="sc-privacy-note"><Text className="sc-setting-name">摄像头与麦克风都处于 OFF</Text><Text>当前没有申请媒体权限，没有录音、录像或音视频上传。后续媒体能力须由你主动开启。</Text></View><View className="sc-privacy-note"><Text className="sc-setting-name">当前是本机单档案安装</Text><Text>账号登录、跨设备同步与云部署尚未启用。界面中的记录不构成诊断。</Text></View>
        </SectionCard>
      </View>
      <View className="sc-settings-column">
        <SectionCard title="存储与连接" eyebrow="当前服务信息">
          <ResourceNotice {...settings} />{settings.status === 'ready' && settings.data && <View className="sc-settings-facts"><View><Text>API</Text><Text className="sc-fact-value">{settings.data.api_base}</Text></View><View><Text>存储状态</Text><Text>{source === 'demo' ? '演示不写入真实存储' : componentStateLabels[database || 'unknown']}</Text></View><View><Text>保留时间</Text><Text>{settings.data.storage.retention_days > 0 ? `${settings.data.storage.retention_days} 天 · 手动维护` : '不自动删除 · 手动维护'}</Text></View><View><Text>原始语音文本</Text><Text>{settings.data.storage.raw_text_saved ? '现有服务可能保存于本机' : '当前模式不保存'}</Text></View></View>}
          <Text className="sc-setting-footnote">此页显示服务信息，不会删除或迁移任何记录。</Text>
        </SectionCard>
        <SectionCard title="服务状态" eyebrow="文字状态，与颜色无关">
          <ResourceNotice {...system} />{components && <View className="sc-system-list">{visibleComponentNames.map(key => {
            const value = components[key];
            return <View key={key} className="sc-system-row"><View><Text className="sc-setting-name">{componentLabel(key)}</Text><Text className="sc-system-reason">{value.reason}</Text></View><Text className={`sc-system-status sc-system-status--${value.status}`}>{componentStateLabels[value.status]}</Text></View>;
          })}</View>}
          <Text className="sc-setting-footnote">以上模型与设备状态来自现有后端。它们不表示当前客户端已申请媒体权限或开始采集。</Text>
        </SectionCard>
      </View>
    </View>
  </AppShell>;
}

export default withClientErrorBoundary(SettingsPage);
