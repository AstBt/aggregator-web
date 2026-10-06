import { onBeforeUnmount, ref } from 'vue';

/* 抽屉宽度拖拽：右侧抽屉从左缘手柄拖动，松开后记住宽度（按 key 分别记忆）。
   手柄元素需为 .drawer-resize，并由使用方渲染在抽屉内部左缘。 */

const LS_PREFIX = 'drawer-width:';
const MIN_W = 360;
const MAX_W = 1280;

const clamp = (w) => Math.max(MIN_W, Math.min(w, window.innerWidth - 48));

function storedWidth(key, fallback) {
  try {
    const v = Number(localStorage.getItem(LS_PREFIX + key));
    if (Number.isFinite(v) && v >= MIN_W) return clamp(v);
  } catch {
    /* 隐私模式等场景下 localStorage 不可用，回退默认宽度 */
  }
  return fallback;
}

export function useDrawerResize(key, defaultWidth = 540) {
  const width = ref(storedWidth(key, defaultWidth));
  let startX = 0;
  let startW = 0;

  const stopDrag = () => {
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', stopDrag);
    window.removeEventListener('pointercancel', stopDrag);
    document.body.classList.remove('col-resizing');
    try {
      localStorage.setItem(LS_PREFIX + key, String(width.value));
    } catch {
      /* 忽略存储失败 */
    }
  };
  const onMove = (e) => {
    // 抽屉贴右缘：向左拖（clientX 变小）变宽，向右拖变窄
    width.value = clamp(startW + (startX - e.clientX));
  };

  function startResize(e) {
    e.preventDefault();
    startX = e.clientX;
    startW = width.value;
    document.body.classList.add('col-resizing');
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', stopDrag);
    window.addEventListener('pointercancel', stopDrag);
  }

  onBeforeUnmount(stopDrag);

  return { width, startResize };
}
