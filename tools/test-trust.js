// test-trust.js —— 术语来源标记的解析逻辑测试。
//
// 为什么值得单独测：
//   这部分"错了不会崩" —— parseTermLine 解析失败只是不打标记，
//   界面上看不出异常。**静默失效是最难发现的一类问题。**
//
// 测三件事：
//   ① parseTermLine  把一行术语文本拆成 { en, rest, claimsZh }
//   ② splitZh        把 "译名（解释）" 拆成译名和解释
//   ③ 两者配合后，"有译名但没出处"必须能被识别出来
//      —— 这是"可信"这条线的核心信号：模型自己编的译名要显眼
//
// 用法： node tools/test-trust.js

const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'demo', 'reader_flow.html'), 'utf8');

function grab(name) {
  const m = src.match(new RegExp('function ' + name + '\\([\\s\\S]*?\\n  \\}'));
  if (!m) throw new Error('找不到 ' + name);
  return m[0];
}

// 停用词表也从源码里取，别在测试里另写一份
//  （之前就吃过这个亏：测试里截断了表，导致 However 被误判成术语）
const stopM = src.match(/const TERM_STOP_EN = new Set\(\([\s\S]*?\)\.split\(' '\)\);/);
if (!stopM) throw new Error('找不到 TERM_STOP_EN');

// eslint-disable-next-line no-new-func
const fns = new Function(
  stopM[0] + '\n' + grab('parseTermLine') + '\n' + grab('splitZh') + '\n' +
  (src.match(/const TERM_HEAD = [\s\S]*?;/) || [''])[0] + '\n' +
  (src.match(/const RE_TERM_EQ = [^\n]*/) || [''])[0] + '\n' +
  (src.match(/const RE_TERM_PAREN = [^\n]*/) || [''])[0] + '\n' +
  grab('isTermSection') + '\n' + grab('looksLikeTerm') + '\n' +
  grab('stripModalPrefix') + '\n' +
  grab('stripTermQuotes') + '\n' + grab('extractTermsFromSection') + '\n' +
  (src.match(/const PROMPT_LEAK = \[[\s\S]*?\];/) || [''])[0] + '\n' +
  grab('isPromptLeak') + '\n' + grab('normSection') + '\n' +
  grab('headerOf') + '\n' +
  grab('normForCompare') + '\n' + grab('looksSame') + '\n' +
  grab('ensureBreaks') + '\n' +
  grab('termExampleFor') + '\n' +
  (src.match(/const TERM_EX_EN = [^\n]*/) || [''])[0] + '\n' +
  (src.match(/const TERM_EX_ZH = [^\n]*/) || [''])[0] + '\n' +
  'return { parseTermLine, splitZh, isTermSection, looksLikeTerm, extractTermsFromSection, isPromptLeak, normSection, headerOf, stripTermQuotes, termExampleFor, looksSame, ensureBreaks };'
)();
const { parseTermLine, splitZh, isTermSection, looksLikeTerm,
        extractTermsFromSection, isPromptLeak, normSection,
        headerOf, stripTermQuotes, termExampleFor, looksSame, ensureBreaks } = fns;

// 复现 renderBody 的判定：一行文本会不会被当成术语行渲染
function wouldRenderAsTerm(line) {
  let t = String(line || '').trim();
  if (!t) return 'blank';
  let section = '';
  const h = /^\u3010(.{1,14}?)\u3011\s*([\s\S]*)$/.exec(t);
  if (h) {
    section = h[1];
    t = h[2].trim();
    if (!t) return 'header';
  }
  const p = parseTermLine(t);
  if (p && (isTermSection(section) || looksLikeTerm(p))) return 'term';
  return 'text';
}

let pass = 0, fail = 0;
function eq(actual, want, label) {
  const ok = JSON.stringify(actual) === JSON.stringify(want);
  if (ok) { pass++; console.log('  ✓ ' + label); }
  else {
    fail++;
    console.log('  ✗ ' + label);
    console.log('      期望: ' + JSON.stringify(want));
    console.log('      实得: ' + JSON.stringify(actual));
  }
}

console.log('='.repeat(74));
console.log('术语来源标记的解析逻辑');
console.log('='.repeat(74));

console.log('\n① parseTermLine');
eq(parseTermLine('panorama stitching = 全景拼接（把多张照片拼成一张宽幅图）'),
   { en: 'panorama stitching', rest: '全景拼接（把多张照片拼成一张宽幅图）', claimsZh: true },
   '有译名（= 号）');

eq(parseTermLine('computer vision（用计算机处理视觉信息的技术）'),
   { en: 'computer vision', rest: '用计算机处理视觉信息的技术', claimsZh: false },
   '只有解释（全角括号）');

eq(parseTermLine('QR code (a scannable code)'),
   { en: 'QR code', rest: 'a scannable code', claimsZh: false },
   '只有解释（半角括号）');

eq(parseTermLine('这是一句普通正文，不是术语行。'), null, '中文正文 -> null');
eq(parseTermLine('【词】'), null, '分节标题 -> null');
eq(parseTermLine('1. 编号开头的正文'), null, '编号开头 -> null');

eq(parseTermLine('panorama-stitching algorithm = 全景拼接算法（多图合成宽幅）').en,
   'panorama-stitching algorithm', '带连字符与多词');

eq(parseTermLine('  spike sorting  =  锋电位分类（神经元放电归类）'),
   { en: 'spike sorting', rest: '锋电位分类（神经元放电归类）', claimsZh: true },
   '多余空格也能处理');

console.log('\n\u2460b \u4e2d\u6587\u672f\u8bed\uff08\u4e2d\u6587\u6587\u7ae0\u4e5f\u8981\u80fd\u89e3\u6790\uff09');
{
  // \u5b9e\u6d4b\u53cd\u9988\uff1a\u4e2d\u6587\u8bba\u6587\u7684\u672f\u8bed\u8282\u53ea\u5217\u4e86\u4e00\u4e32\u8bcd\u3001\u6ca1\u89e3\u91ca\u3002
  //  \u539f\u56e0\u4e4b\u4e00\uff1aparseTermLine \u8981\u6c42\u4ee5\u3010\u82f1\u6587\u5b57\u6bcd\u3011\u5f00\u5934\uff0c
  //  \u4e2d\u6587\u672f\u8bed\u5168\u90e8\u89e3\u6790\u5931\u8d25\uff0c\u9000\u5316\u6210\u666e\u901a\u6587\u672c\u3002
  eq(parseTermLine('\u795e\u7ecf\u632f\u8361\uff08\u795e\u7ecf\u5143\u7fa4\u7684\u540c\u6b65\u7535\u6d3b\u52a8\uff09'),
     { en: '\u795e\u7ecf\u632f\u8361', rest: '\u795e\u7ecf\u5143\u7fa4\u7684\u540c\u6b65\u7535\u6d3b\u52a8', claimsZh: false },
     '\u4e2d\u6587\u672f\u8bed + \u62ec\u53f7\u89e3\u91ca');

  eq(parseTermLine('\u9ed8\u8ba4\u6a21\u5f0f\u7f51\u7edc = \u4f11\u606f\u65f6\u4ecd\u6d3b\u8dc3\u7684\u8111\u533a\u7f51\u7edc'),
     { en: '\u9ed8\u8ba4\u6a21\u5f0f\u7f51\u7edc', rest: '\u4f11\u606f\u65f6\u4ecd\u6d3b\u8dc3\u7684\u8111\u533a\u7f51\u7edc', claimsZh: true },
     '\u4e2d\u6587\u672f\u8bed + \u7b49\u53f7\u5f62\u5f0f');

  eq(parseTermLine('\u9ed8\u8ba4\u6a21\u5f0f\u7f51\u7edc'), null,
     '\u53ea\u6709\u8bcd\u3001\u6ca1\u6709\u89e3\u91ca -> \u4e0d\u5f53\u672f\u8bed\u884c\uff08\u907f\u514d\u5e72\u5217\u4e00\u4e32\u8bcd\uff09');

  eq(parseTermLine('\u8fd9\u662f\u4e00\u53e5\u666e\u901a\u7684\u4e2d\u6587\u6b63\u6587\uff0c\u4e0d\u662f\u672f\u8bed\u3002'), null,
     '\u4e2d\u6587\u6b63\u6587 -> null');
}

console.log('\n\u2460c 术语节整段抽取（模型怎么排版都要能认）');
{
  // 实测截图：模型把好几条术语挤在一行用分号隔开，
  //  还有的把词和解释分成两行、或用「」把词包起来。
  //  按行解析只能认出第一条 —— 改成整段抽取才能全覆盖。
  function terms(t) { return extractTermsFromSection(t).map(function (x) { return x.en; }); }

  eq(terms('神经振荡（神经元群的同步电活动）'),
     ['神经振荡'], '一行一条');

  eq(terms('顶叶（负责视觉信息处理）；大脑网络（多个脑区连接而成）'),
     ['顶叶', '大脑网络'], '分号隔开挤在一行');

  eq(terms('神经科学 （位于大脑前侧的区域）'),
     ['神经科学'], '词与解释之间有空白');

  eq(terms('「大脑动态平衡」（神经系统动态稳定性）'),
     ['大脑动态平衡'], '词被「」包起来也能剥掉');

  var mixed = '神经科学 （位于大脑前侧的区域）；顶叶（主要负责视觉信息处理）；' +
    '大脑网络（多个脑区连接而成）「大脑动态平衡」（保持平衡）；' +
    '「神经通质」（信息传送）;谷氨酸能（一种调节物质）。';
  eq(terms(mixed),
     ['神经科学', '顶叶', '大脑网络', '大脑动态平衡', '神经通质', '谷氨酸能'],
     '混排（用户截图那种）');

  eq(terms('默认模式网络'), [], '只有词、没有解释 -> 不算术语');
  eq(terms('这是一句普通的中文正文，没有术语。'), [], '普通正文不会被抽成术语');
}

console.log('\n\u2460d 渲染层兜底（小模型不守格式是常态）');
{
  // ---- prompt 原文被抄进输出 ----
  //  实测泄漏出来的两句，以及从 prompt 里抄来的语气词。
  var leaks = [
    '只输出上面三节，不要重复我给你的内容。',
    '说明文字用中文，但「词」那一节的术语要保留英文原词。',
    '不要写 "词 = 另一个词" 这种形式。',
    '每节标题单独占一行',
  ];
  leaks.forEach(function (x) {
    eq(isPromptLeak(x), true, '认出 prompt 泄漏：' + x.slice(0, 14) + '…');
  });
  eq(isPromptLeak('神经科学研究证实了前额叶的核心作用。'), false, '正文不会被误判成泄漏');
  // 太长的行不判为泄漏（prompt 的句子都很短）
  eq(isPromptLeak('只输出上面三节' + '补充'.repeat(40)), false, '很长的行不判泄漏');

  // ---- prompt 里的语气词被抄成术语前缀 ----
  eq(stripTermQuotes('必须 工作记忆'), '工作记忆', '剥掉「必须」');
  eq(stripTermQuotes('不需要 理论挑战'), '理论挑战', '剥掉「不需要」');
  eq(stripTermQuotes('不要 竞争性理论'), '竞争性理论', '剥掉「不要」');
  eq(stripTermQuotes('「大脑动态平衡」'), '大脑动态平衡', '仍然会剥引号');
  eq(stripTermQuotes('工作记忆'), '工作记忆', '正常术语不受影响');

  // ---- 标题四种形式都要认 ----
  eq(headerOf('【词】').name, '词', '标题形式一：【词】');
  eq(headerOf('词').name, '词', '标题形式二：词');
  eq(headerOf('词:').name, '词', '标题形式三：词:');
  eq(headerOf('【词】：').name, '词', '标题形式四：【词】：');
  eq(headerOf('【词】工作记忆（高级认知功能）').rest, '工作记忆（高级认知功能）',
     '标题与内容同行时要能拆开');
  eq(headerOf('这是一句正文'), null, '正文不会被当成标题');

  // ---- 节名归一化 ----
  eq(normSection('术语'), '词', '【术语】也算词那一节');
  eq(normSection('词'), '词', '【词】');
  eq(normSection('难点'), '难点', '【难点】');
  eq(normSection('这句在说什么'), '这句在说什么', '【这句在说什么】');
}

console.log('\n\u2460e 术语例子按句子语言选（中英混排不能挑错）');
{
  // 实测：英文句子被写成「神经元振荡同步（neurotransmission synchronization）」
  //  —— 术语中文、括号英文，正好反了。根因是 prompt 同时给了中英两行例子。
  var exEn = termExampleFor('Furthermore, it reveals the critical roles played by neural oscillatory synchronization.');
  eq(/neuronal oscillatory/.test(exEn), true, '英文句子 -> 例子以英文术语打头');
  eq(/神经振荡同步/.test(exEn), true, '英文句子的例子里括号内是中文解释');

  var exZh = termExampleFor('神经科学研究证实了前额叶在工作记忆中的核心作用。');
  eq(/神经振荡同步/.test(exZh), true, '中文句子 -> 例子以中文术语打头');
  eq(/大脑不同区域/.test(exZh), true, '中文句子的括号里是解释（不是纯译名）');

  // 真实的中英混排：中文句子嵌一个英文缩写
  eq(termExampleFor('工作记忆的缺陷被认为是 ADHD 患者的注意力调控困难。') === exZh,
     true, '中文句子嵌英文缩写 -> 按中文格式');
  // 真实的英文句子嵌一个中文词（少见，但也要对）
  eq(termExampleFor('This finding is called 工作记忆 in Chinese literature.') === exEn,
     true, '英文句子嵌中文词 -> 按英文格式');
  // 说明：构造"中英各占一半"的句子去判语言没有意义 ——
  //  那种句子的两种格式都说得通，机器判哪个都不算错。
  eq(termExampleFor('') === exEn, true, '空句子按英文格式（保守）');
}

console.log('\n\u2460f 整段重复输出要能截断（小模型的重复退化）');
{
  // 实测：重新生成时整块【这句在说什么】【词】【难点】重复 3~4 遍。
  //  判据是第一节标题再次出现 —— 静态检查，确认守卫还在。
  var rb = src.match(/function renderBody\(bodyEl, text, srcText\) \{[\s\S]*?\n  \}/);
  eq(!!rb, true, '找到 renderBody');
  eq(rb ? /sawFirstSection/.test(rb[0]) : false, true, 'renderBody 里有"见过第一节"的标记');
  eq(rb ? /break;/.test(rb[0]) : false, true, '重复出现时用 break 截断');
  eq(rb ? /这句在说什么/.test(rb[0]) : false, true, '判据用的是第一节标题');
}

console.log('\n\u2460g 模型抄源句 / 重复同一段话');
{
  // 实测（图三）：第一节内容是一大段英文原文，而且连着四条几乎一样的解释。
  var source = 'Psychological reactance refers to an aversive motivational state that is theorized to occur when an individual\'s behavioral freedoms are threatened or eliminated.';

  eq(looksSame(source, source), true, '完全相同的源句被认出');
  eq(looksSame(source, source.replace(/[\s,]+/g, ' ')), true, '只差空格标点也算同一句');
  eq(looksSame(source, '这句讲的是心理反应性，一种当行为自由受威胁时出现的动机状态。'), false,
     '正常的中文讲解不会被误判成抄源句');

  // 重复解释：措辞略有不同
  var a1 = '心理反应性指的是一种厌恶动机的现象，比如使用高自由威胁语言与低状态。';
  var a2 = '心理反应性指的是一种厌恶性的动机现象，比如使用较高威胁个人自由的语言与较低状态。';
  eq(looksSame(a1, a2), true, '措辞略不同的重复解释能被认出');

  // 短句不判重（避免误杀正常的并列术语）
  eq(looksSame('工作记忆', '工作记忆容量'), false, '很短的文本不判重，避免误杀');
  eq(looksSame('前额叶', '顶叶'), false, '并列的术语不会被当成重复');
}

console.log('\n\u2460h 标题与正文挤在同一行也要切开');
{
  // 早先 ensureBreaks 只在"整段几乎没有换行"时才补，
  //  而模型会把标题和正文挤在一行、别的行又有换行 -> 前提不成立 -> 没切开。
  var mixed = '【这句在说什么】文章揭示了脑功能同步的作用。\n【词】\n神经功能同步（大脑不同区域活动节奏一致）\n【难点】句子涉及复合概念。';
  var out = ensureBreaks(mixed);
  eq(/^【这句在说什么】$/m.test(out), true, '标题独占一行');
  eq(/^【词】$/m.test(out), true, '【词】独占一行');
  eq(/^【难点】$/m.test(out), true, '【难点】独占一行');
  eq(out.indexOf('【这句在说什么】文章') < 0, true, '标题后面不再紧跟正文');

  // 本来就已经分好行的，不要被改坏
  var ok = '【词】\n工作记忆（短期存储与处理信息的功能）\n';
  eq(ensureBreaks(ok), '【词】\n工作记忆（短期存储与处理信息的功能）',
     '本来就分好行的不会被改坏');
}

console.log('\n\u2461 splitZh');
eq(splitZh('全景拼接（把多张照片拼成一张宽幅图）'),
   { name: '全景拼接', note: '（把多张照片拼成一张宽幅图）' },
   '标准形态（全角括号不加空格）');

eq(splitZh('全景拼接'), { name: '全景拼接', note: '' }, '没有括号');
eq(splitZh('全景拼接 (panorama stitching)'),
   { name: '全景拼接', note: ' (panorama stitching)' }, '半角括号前留一个空格');

// 译名里可能含全角括号之外的东西，不能切坏
eq(splitZh('锋电位分类（spike sorting，神经元放电的归类）').name,
   '锋电位分类', '括号里还有逗号也不影响');

console.log('\n\u2462 关键设计：模型给的译名一律丢弃');
{
  // 实测：模型编出过 "OpenCV = 奥克拉夫视网膜"。
  //  只标个警告不够 —— 那行字已经写出来了，用户扫一眼就可能当真。
  //  现在改成：译名只来自外部查证；模型写什么 "= xxx" 都不采信。
  //
  //  这里用 renderBody 的判定逻辑做等价验证：
  //    有出处 -> 显示 " = 译名 （解释）"
  //    没出处 -> 只显示 " （解释）"，即使模型写了等号
  function renderTerm(p, src) {
    const parts = splitZh(p.rest);
    const note = parts.note || ('\uFF08' + parts.name + '\uFF09');
    return src ? (' = ' + src + ' ' + note) : (' ' + note);
  }

  const p1 = parseTermLine('OpenCV = \u5965\u514b\u62c9\u592b\u89c6\u7f51\u819c');
  eq(renderTerm(p1, null), ' \uFF08\u5965\u514b\u62c9\u592b\u89c6\u7f51\u819c\uFF09',
     '\u6a21\u578b\u7f16\u7684\u8bd1\u540d\u4e0d\u4f1a\u51fa\u73b0\uff08\u65e0\u51fa\u5904\u65f6\u53ea\u7ed9\u89e3\u91ca\uff09');

  const p2 = parseTermLine('computer vision = \u6570\u5b57\u89c6\u89c9\u6280\u672f\uff08\u7528\u8ba1\u7b97\u673a\u5904\u7406\u56fe\u50cf\uff09');
  eq(renderTerm(p2, '\u8ba1\u7b97\u673a\u89c6\u89c9'),
     ' = \u8ba1\u7b97\u673a\u89c6\u89c9 \uFF08\u7528\u8ba1\u7b97\u673a\u5904\u7406\u56fe\u50cf\uFF09',
     '\u6709\u51fa\u5904\u65f6\u7528\u5916\u90e8\u8bd1\u540d\uff0c\u6a21\u578b\u5199\u7684\u201c\u6570\u5b57\u89c6\u89c9\u6280\u672f\u201d\u88ab\u4e22\u5f03');

  const p3 = parseTermLine('panorama stitching\uff08\u628a\u591a\u5f20\u7167\u7247\u62fc\u6210\u4e00\u5f20\u5bbd\u5e45\u56fe\uff09');
  eq(renderTerm(p3, null),
     ' \uFF08\u628a\u591a\u5f20\u7167\u7247\u62fc\u6210\u4e00\u5f20\u5bbd\u5e45\u56fe\uFF09',
     '\u53ea\u6709\u89e3\u91ca\u7684\u60c5\u51b5\u4e0b\u6b63\u5e38\u663e\u793a');

  eq(renderTerm(p3, '\u5168\u666f\u62fc\u63a5'),
     ' = \u5168\u666f\u62fc\u63a5 \uFF08\u628a\u591a\u5f20\u7167\u7247\u62fc\u6210\u4e00\u5f20\u5bbd\u5e45\u56fe\uFF09',
     '\u540c\u4e00\u6761\u672f\u8bed\u67e5\u5230\u8bd1\u540d\u540e\u5c31\u5e26\u4e0a\u8bd1\u540d');
}

console.log('\n④ 格式偏离时的容错（模型不守格式是常态）');
{
  // 实测踩到：模型把标题和内容写在同一行 ->
  //   标题识别失败 -> 术语行判定从不触发 -> 标记和订正按钮全都不显示
  eq(wouldRenderAsTerm(
      '\u3010\u8bcd\u3011Application areas = \u5e94\u7528\u9886\u57df\uff08\u6307\u67d0\u79cd\u6280\u672f\u7684\u5e94\u7528\uff09'),
     'term', '标题与内容同行也要能识别出术语');

  eq(wouldRenderAsTerm('Technology = \u6280\u672f\uff08\u79d1\u6280\u9886\u57df\u4f7f\u7528\u7684\u7cfb\u7edf\uff09'),
     'term', '标题之后的行');

  eq(wouldRenderAsTerm('\u3010\u672f\u8bed\u3011spike sorting = \u950b\u7535\u4f4d\u5206\u7c7b'),
     'term', '模型写成【术语】也认');

  eq(wouldRenderAsTerm('\u3010\u8fd9\u53e5\u5728\u8bf4\u4ec0\u4e48\u3011'), 'header', '标题独占一行');
  eq(wouldRenderAsTerm('\u3010\u8bcd\u3011'), 'header', '空的【词】');

  // 不能把正文误判成术语 —— 这是放宽判断后最需要防的
  eq(wouldRenderAsTerm('However (as noted above), this is fine.'),
     'text', 'However 开头的正文不能当术语');
  eq(wouldRenderAsTerm('The results (shown in Fig. 3) were significant.'),
     'text', 'The 开头的正文不能当术语');
  eq(wouldRenderAsTerm('\u8fd9\u4e2a\u53e5\u5b50\u5217\u4e3e\u4e86\u5e94\u7528 computer vision \u6280\u672f\u7684\u9886\u57df\u3002'),
     'text', '中文正文');
}

console.log('\n\u2463 两套 prompt（防止约束无限堆积）');
{
  // 这一条是有来历的：
  //   我连着几轮往 prompt 里追加约束（防编造、允许说不确定、
  //   只列专业术语、标题独占一行…），每条单独看都合理，
  //   累计到 763 字符、12 个【】标记时小模型崩了 ——
  //   它把我用【】写的"元指令"当成要输出的标题，
  //   真的输出了一行"【每段的标题】"，正文退化成英文复述。
  //   压到 352 字符 / 3 个【】之后就正常了。
  //
  //   按后端分两套：
  //     lite  给浏览器内置模型、本地 Ollama 这类小模型
  //     full  给云端大模型
  //
  //   这里把这件"容易失控"的事变成可检查的：
  //     · 每套的【】必须恰好是那三个输出标题
  //     · 每套不超过 500 字符
  //     · 精简版必须真的比完整版短
  //
  //   注意写法：用【位置切片】而不是拼正则 ——
  //   上一版把正则经三层字符串拼出来，转义全乱了，抽到的内容根本不对。
  const EXPECT = '\u3010这句在说什么\u3011,\u3010词\u3011,\u3010难点\u3011';

  function promptText(startMark, endMark) {
    const a = src.indexOf(startMark);
    if (a < 0) return null;
    const b = src.indexOf(endMark, a + startMark.length);
    if (b < 0) return null;
    const block = src.slice(a, b);
    const lits = block.match(/'((?:[^'\\]|\\.)*)'/g) || [];
    return lits.map(x => x.slice(1, -1)).join('').replace(/\\n/g, '\n');
  }

  const lite = promptText('      lite:', '      full:');
  const full = promptText('      full:', '      build(');

  if (!lite || !full) {
    fail++;
    console.log('  \u2717 找不到两套 prompt（lite / full）');
  } else {
    [['精简版', lite], ['完整版', full]].forEach(([label, text]) => {
      eq(text.length <= 500, true,
         label + '长度 ' + text.length + ' 字符（上限 500）');
      const marks = text.match(/\u3010[^\u3011]{1,20}\u3011/g) || [];
      eq(marks.join(','), EXPECT,
         label + '的【】只出现在三个输出标题上（实得 ' + marks.length + ' 个）');
      eq(/\u4e09\u8282/.test(text), true, label + '指明了输出节数');
    });
    eq(lite.length < full.length, true,
       '精简版（' + lite.length + '）短于完整版（' + full.length + '）');
  }
}

console.log('\n' + '='.repeat(74));
if (fail === 0) console.log('全部通过 ✓  （' + pass + ' 项）');
else console.log('未通过 ' + fail + ' 项（共 ' + (pass + fail) + ' 项）');
console.log('='.repeat(74));
process.exit(fail === 0 ? 0 : 1);
