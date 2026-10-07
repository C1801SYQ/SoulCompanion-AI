import { Text, View } from '@tarojs/components';
import { AccessibleButton as Button } from '../../components/AccessibleButton';
import { AppShell, PageHeader } from '../../components/AppShell';
import { withClientErrorBoundary } from '../../components/ClientErrorBoundary';
import { componentLabel, componentStateLabels, visibleComponentNames } from '../../components/format';
import { ResourceNotice, SectionCard, StatusPill } from '../../components/Primitives';
import { useResource } from '../../hooks/useResource';
import { useCompanion } from '../../state/AppProvider';
import { useSession } from '../../state/SessionProvider';
import { deviceText } from '../../components/mediaText';
import { CloudAccount } from '../../components/CloudAccount';

function SettingsPage() {
  const { api, source, setSource, motionEnabled, setMotionEnabled, demoOnly } = useCompanion();
  const { stop, state: mediaState } = useSession();
  const settings = useResource(`settings:${source}`, () => api.getSettings());
  const system = useResource(`settings:system:${source}`, () => api.getSystem(), 10000);
  const database = system.status === 'ready' ? system.data?.components.database.status : undefined;
  const components = system.status === 'ready' ? system.data?.components : null;
  function chooseSource(next: 'real' | 'demo') {
    if (next === source) return;
    void stop('source_change');
    setSource(next);
  }
  return <AppShell page="settings">
    <PageHeader eyebrow="SETTINGS · 设置" title="以你的节奏，安心陪伴。" description="了解数据从哪里来，选择舒服的体验方式。" />
    <View className="sc-profile"><View className="sc-profile-avatar" ariaHidden><View /></View><View><Text className="sc-profile-title">欢迎来到你的陪伴空间</Text><Text className="sc-body-muted">本机预览与云端账号资料各自独立</Text></View><StatusPill>V2 体验预览</StatusPill></View>
    <View className="sc-settings-grid">
      <View className="sc-settings-column">
        <CloudAccount />
        <SectionCard title="数据来源" eyebrow="你可以随时选择">
          <View className="sc-mode-options"><Button id="mode-real" className={`sc-mode-option ${source === 'real' ? 'sc-mode-option--selected' : ''}`} aria-pressed={source === 'real'} disabled={demoOnly} onClick={() => chooseSource('real')}><View className="sc-mode-option-heading"><Text>REAL · 真实数据</Text><Text className="sc-mode-check">{source === 'real' ? '已选择' : demoOnly ? '此构建不可用' : '选择'}</Text></View><Text className="sc-body-muted">读取配置的本机服务，未连接时显示离线。</Text></Button><Button id="mode-demo" className={`sc-mode-option ${source === 'demo' ? 'sc-mode-option--selected' : ''}`} aria-pressed={source === 'demo'} onClick={() => chooseSource('demo')}><View className="sc-mode-option-heading"><Text>DEMO · 合成示例</Text><Text className="sc-mode-check">{source === 'demo' ? '已选择' : '选择'}</Text></View><Text className="sc-body-muted">情绪和报告为合成示例，不发送真实数据请求。仍可主动体验本地摄像头和麦克风；设备预览不等于情绪推理。</Text></Button></View>
          <Text className="sc-setting-footnote">切换来源会结束本客户端当前采集。任何数据模式都可再次主动开始本地预览。另行运行的旧设备服务需要单独停止。</Text>
        </SectionCard>
        <SectionCard title="让体验更舒适" eyebrow="动画与动态效果">
          <View className="sc-setting-row"><View><Text className="sc-setting-name">Emotion Orb 呼吸动画</Text><Text className="sc-body-muted">轻柔变化，始终尊重系统的减少动态效果设置。</Text></View><Button id="motion-toggle" className={`sc-toggle ${motionEnabled ? 'sc-toggle--on' : ''}`} role="switch" aria-checked={motionEnabled} ariaLabel={`Emotion Orb 动画，${motionEnabled ? '开启' : '关闭'}`} onClick={() => setMotionEnabled(!motionEnabled)}><View className="sc-toggle-knob" /><Text>{motionEnabled ? '开启' : '关闭'}</Text></Button></View>
        </SectionCard>
        <SectionCard title="隐私与自主选择" eyebrow="知道发生了什么">
          <View className="sc-privacy-note"><Text className="sc-setting-name">{deviceText('Camera', mediaState.capture.camera)} · {deviceText('Mic', mediaState.capture.microphone)}</Text><Text>设备只在陪伴页主动开始后工作。结束、离开陪伴页、后台或设备断网都会停止采集，回来后不会自动恢复。当前原始音视频不上传、不长期保存；平台生成的临时片段在处理后清理。现有情绪服务是否连接，不影响本地预览。</Text></View><View className="sc-privacy-note"><Text className="sc-setting-name">云端资料有账号与档案边界</Text><Text>仅登录并选择档案后同步会话起止时间。本机旧情绪记录不会自动迁移；摄像头画面、麦克风片段、设备名称与设备编号不会上传。界面中的记录不构成诊断。</Text></View>
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
