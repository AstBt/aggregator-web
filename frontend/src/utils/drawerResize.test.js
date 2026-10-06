// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import { defineComponent, h } from 'vue';

import { useDrawerResize } from './drawerResize';

function setup(key = 'test-drawer', def = 540) {
  let api;
  const Comp = defineComponent({
    setup() {
      api = useDrawerResize(key, def);
      return () => h('div');
    },
  });
  mount(Comp);
  return api;
}

const evt = (clientX) => ({ clientX, preventDefault: () => {} });
const move = (clientX) => window.dispatchEvent(new MouseEvent('pointermove', { clientX }));
const up = () => window.dispatchEvent(new MouseEvent('pointerup'));

describe('抽屉宽度拖拽', () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.className = '';
  });

  it('默认为传入宽度', () => {
    expect(setup('a', 540).width.value).toBe(540);
    expect(setup('b', 720).width.value).toBe(720);
  });

  it('向左拖变宽、向右拖变窄', () => {
    const { width, startResize } = setup();
    startResize(evt(500));
    move(400);
    expect(width.value).toBe(640);
    move(350);
    expect(width.value).toBe(690);
    up();
  });

  it('宽度被钳制在最小值与视口上限之间', () => {
    const innerW = window.innerWidth; // jsdom 默认 1024
    const { width, startResize } = setup();
    startResize(evt(0));
    move(-1000);
    expect(width.value).toBe(innerW - 48);
    move(1000);
    expect(width.value).toBe(360);
    up();
  });

  it('松手后写入 localStorage，下次打开记忆宽度', () => {
    const first = setup();
    first.startResize(evt(300));
    move(200);
    up();
    expect(localStorage.getItem('drawer-width:test-drawer')).toBe('640');
    expect(setup().width.value).toBe(640);
  });
});
