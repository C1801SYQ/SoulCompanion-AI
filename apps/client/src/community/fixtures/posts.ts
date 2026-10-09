import type { CommunityPostPreview } from '../types';

/** Handwritten fictional examples. Never mixed with CloudBase records or real people. */
export const EXAMPLE_POSTS: readonly CommunityPostPreview[] = [
  {
    id: 'example-01', title: '先听完，再一起想办法', summary: '一次日常交流的合成故事：先给孩子一点表达的时间，也给自己一点停顿。',
    body: '示例中的家长原本很想马上给建议，后来试着先听完一句话，再问：“你希望我听一听，还是一起想办法？”\n\n这只是虚构的日常交流片段，展示社区文字内容的样子。每个家庭的节奏不同，不是专业指导。',
    author: { displayName: '慢慢来家长', source: 'example' }, publishedAt: '2026-10-08T18:00:00+08:00', age: '6-8', topic: 'parent-child', source: 'example',
  },
  {
    id: 'example-02', title: '把“快一点”换成一次小邀请', summary: '出门前，虚构家长尝试把催促说得具体一些，一起完成一件小事。',
    body: '这是合成示例。家长在出门前说：“我们一起找好鞋子，然后到门口碰个拳。”过程没有总是顺利，但留下一点一起做事的感觉。\n\n这里没有真实孩子信息，也没有固定的育儿答案。',
    author: { displayName: '留白家长', source: 'example' }, publishedAt: '2026-10-08T09:00:00+08:00', age: '3-5', topic: 'parent-child', source: 'example',
  },
  {
    id: 'example-03', title: '忙乱的一天，给自己一口气的时间', summary: '照顾小宝宝的日常有忙碌也有疲惫。这个示例记录家长短暂休息的想法。',
    body: '合成示例中的家长把一天分成很小的片段。在家人接手照看的一会儿，坐下来喝一口水，不要求自己每一刻都做得完美。\n\n这是虚构交流素材，不包含医疗、睡眠训练或安全照护建议。',
    author: { displayName: '晴窗家长', source: 'example' }, publishedAt: '2026-10-07T17:30:00+08:00', age: '0-2', topic: 'emotional-support', source: 'example',
  },
  {
    id: 'example-04', title: '难过的时候，也可以暂时不找答案', summary: '示例里的一次聊天从“发生了什么”开始，留出表达感受的空间。',
    body: '这是一段虚构故事。家长和孩子聊天时，先听见了“今天有点难过”，没有马上猜原因，而是约好等想说的时候再说。\n\n文字只是用于体验页面，不是对情绪或心理健康的判断。',
    author: { displayName: '小步家长', source: 'example' }, publishedAt: '2026-10-07T08:00:00+08:00', age: '9-12', topic: 'emotional-support', source: 'example',
  },
  {
    id: 'example-05', title: '日常清单里，留一格给家长自己', summary: '一份虚构的家庭日常清单，除了要做的事，也留了一小格记录感受。',
    body: '合成示例：家长在日常清单最后加了一格“今天我需要什么”。有时写的是休息，有时是一顿不着急的饭。\n\n示例不描述真实婴幼儿，也不提供喂养或健康建议。',
    author: { displayName: '米色家长', source: 'example' }, publishedAt: '2026-10-06T18:00:00+08:00', age: '0-2', topic: 'daily-habits', source: 'example',
  },
  {
    id: 'example-06', title: '一起整理角落，不急着做到完美', summary: '收拾玩具的虚构片段：从一个小角落开始，和孩子一起做一点。',
    body: '这是一条合成内容。示例中的家长和孩子先把几个玩具放回同一处，再一起看看还想整理哪里。\n\n家庭生活不需要都一样，这里只展示可以分享的日常文字。',
    author: { displayName: '暖灯家长', source: 'example' }, publishedAt: '2026-10-06T10:00:00+08:00', age: '3-5', topic: 'daily-habits', source: 'example',
  },
  {
    id: 'example-07', title: '新的生活节奏，也给家长适应的时间', summary: '入园生活的合成话题：家长也会有期待和不舍，慢慢认识新的节奏。',
    body: '虚构家长在这条示例里记录了对新日常的期待。没有具体学校、园所或孩子身份，只有“我们都在适应”的一句话。\n\n这是社区内容结构示例，不是入园干预或专业方案。',
    author: { displayName: '同行家长', source: 'example' }, publishedAt: '2026-10-05T17:00:00+08:00', age: '3-5', topic: 'school-transition', source: 'example',
  },
  {
    id: 'example-08', title: '聊聊放学路上的一个小发现', summary: '放学后的虚构对话不从成绩开始，而从今天注意到的一件小事开始。',
    body: '合成故事中的家长问：“今天有没有一个你想告诉我的小发现？”有时孩子想说，有时不想说，家长也分享了自己的日常。\n\n没有真实学校或个人信息，也不代表适合每个家庭的沟通方法。',
    author: { displayName: '轻风家长', source: 'example' }, publishedAt: '2026-10-05T08:30:00+08:00', age: '6-8', topic: 'school-transition', source: 'example',
  },
  {
    id: 'example-09', title: '一起聊聊“这件事有点难”', summary: '学习遇到困难时的一段合成讨论，重点是说清眼前的感受和需求。',
    body: '虚构示例中的家长和孩子分别说了“我觉得哪里有点难”。讨论没有给出标准答案，只记录了彼此愿意慢慢说的过程。\n\n这里不是学习成绩评价，也不提供心理或教育专业结论。',
    author: { displayName: '向晚家长', source: 'example' }, publishedAt: '2026-10-04T18:00:00+08:00', age: '9-12', topic: 'learning-peers', source: 'example',
  },
  {
    id: 'example-10', title: '朋友的话题，有时候先听就很好', summary: '同伴交流的合成话题：尊重孩子想说多少，也保留家长可以回应的位置。',
    body: '这是一条虚构内容。家长听到关于朋友的一段分享时，没有询问姓名或学校，而是听一听这件事对孩子意味着什么。\n\n示例不包含真实同伴身份，不替代专业帮助。',
    author: { displayName: '有光家长', source: 'example' }, publishedAt: '2026-10-04T10:00:00+08:00', age: '13-15', topic: 'learning-peers', source: 'example',
  },
  {
    id: 'example-11', title: '约一个双方都方便的聊天时间', summary: '青春期沟通的虚构片段：让聊天成为可以商量的事，留一点彼此的空间。',
    body: '合成家长在示例里尝试先问：“什么时候聊比较方便？”这个小问题不一定每次都有答案，但表达了愿意协商的心意。\n\n这是产品预览内容，不是对青春期行为的诊断或保证有效的建议。',
    author: { displayName: '等一等家长', source: 'example' }, publishedAt: '2026-10-03T18:00:00+08:00', age: '13-15', topic: 'adolescence', source: 'example',
  },
  {
    id: 'example-12', title: '面对未来，家长也在学习放慢', summary: '关于未来选择的一段合成交流：把期待说出来，也给不同想法一点位置。',
    body: '虚构家长在这条示例里写下自己的期待，随后想听听孩子的想法。故事没有真实升学信息、学校名称或结果。\n\n每个家庭的情况不同，文字仅用于呈现社区交流的方式。',
    author: { displayName: '远望家长', source: 'example' }, publishedAt: '2026-10-03T09:00:00+08:00', age: '16-18', topic: 'adolescence', source: 'example',
  },
  {
    id: 'example-13', title: '家长的成长，也值得留下几句话', summary: '一段虚构的家长自我回顾：不是打分，只是发现自己正在经历什么。',
    body: '这条合成示例记录了一句“今天我也在学习”。没有成长指标、能力评级或付费门槛，只有虚构家长对日常的一点感受。\n\n真实私有成长记录将在后续阶段实现，这条社区示例并不是已保存的家庭记录。',
    author: { displayName: '慢行家长', source: 'example' }, publishedAt: '2026-10-02T16:00:00+08:00', age: '16-18', topic: 'parent-growth', source: 'example',
  },
  {
    id: 'example-14', title: '给忙碌的自己一句友好的话', summary: '虚构家长在忙碌之后写下一句话：允许有没做完的事，也看见已经做的事。',
    body: '合成内容中的家长在一天结束时写：“我今天已经努力了。”这不是专业练习或疗法，只是一段虚构生活文字。\n\n社区目前只有本地示例，不会将这段文字写入任何家庭档案。',
    author: { displayName: '一盏灯家长', source: 'example' }, publishedAt: '2026-10-02T08:00:00+08:00', age: '6-8', topic: 'parent-growth', source: 'example',
  },
];
