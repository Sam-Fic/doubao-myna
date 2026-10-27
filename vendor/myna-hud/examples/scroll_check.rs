// examples/scroll_check.rs — 验证胶囊“单行 + 宽度封顶 + 旧字往左滚走”。
//
// 模拟豆包流式出字(每 150ms 追加几个字),逐帧断言:
//   * 标签永远只有 1 行;
//   * 胶囊高度全程不变;
//   * 宽度涨到 LABEL_MAX_WIDTH 后不再增长;
//   * 文字溢出后水平 adjustment 停在最右端(最新字可见,旧字滚走)。
//
//   cargo run --release -p myna-hud --example scroll_check
//
// 退出码 0 = 全部通过。需要图形会话(Wayland 或 X11)。

use gtk::glib;
use gtk::prelude::*;
use gtk4 as gtk;
use libadwaita as adw;
use libadwaita::prelude::*;
use myna_hud::pill::LABEL_MAX_WIDTH;
use myna_hud::platform::Platform;
use myna_hud::states::state_to_descriptor;
use myna_hud::window::HudWindow;
use std::cell::RefCell;
use std::collections::BTreeSet;
use std::rc::Rc;

/// 一段远超胶囊宽度的流式识别文本。
const SENTENCE: &str = "今天下午三点我们和设计团队一起开个会讨论新版本的界面交互细节\
以及下个季度需要交付的功能范围顺便确认一下测试排期和发布计划安排";

/// 胶囊除文本外的固定宽度(图标 + 间距 + padding),给断言留的余量。
const CHROME_SLACK: i32 = 160;

fn find<T: IsA<gtk::Widget> + 'static>(widget: &gtk::Widget) -> Option<T> {
    if let Some(found) = widget.downcast_ref::<T>() {
        return Some(found.clone());
    }
    let mut child = widget.first_child();
    while let Some(current) = child {
        if let Some(found) = find::<T>(&current) {
            return Some(found);
        }
        child = current.next_sibling();
    }
    None
}

fn main() {
    let app = adw::Application::builder()
        .application_id("com.canonical.Myna.HudScrollCheck")
        .build();

    app.connect_activate(|app| {
        let hud = HudWindow::new(app, Platform::current().profile);
        hud.window().present();
        let window = hud.window();

        let chars: Vec<char> = SENTENCE.chars().collect();
        let cursor = Rc::new(RefCell::new(0usize));
        let problems = Rc::new(RefCell::new(Vec::<String>::new()));
        let heights = Rc::new(RefCell::new(Vec::<i32>::new()));
        let widths = Rc::new(RefCell::new(Vec::<i32>::new()));
        let scrolled = Rc::new(RefCell::new(false));

        let tick = {
            let (hud, window, chars) = (hud.clone(), window.clone(), chars.clone());
            let (cursor, problems, heights, widths, scrolled) = (
                cursor.clone(),
                problems.clone(),
                heights.clone(),
                widths.clone(),
                scrolled.clone(),
            );
            move || -> glib::ControlFlow {
                let mut at = cursor.borrow_mut();
                if *at >= chars.len() {
                    return glib::ControlFlow::Break;
                }
                let end = (*at + 3).min(chars.len());
                *at = end;
                let text: String = chars[..end].iter().collect();
                drop(at);
                hud.apply_descriptor(state_to_descriptor(Some("recording"), &text));

                // 等这一帧分配完成再采样。
                let window2 = window.clone();
                let (problems2, heights2, widths2, scrolled2) = (
                    problems.clone(),
                    heights.clone(),
                    widths.clone(),
                    scrolled.clone(),
                );
                glib::idle_add_local_once(move || {
                    heights2.borrow_mut().push(window2.height());
                    widths2.borrow_mut().push(window2.width());

                    let label: gtk::Label = find(window2.upcast_ref()).expect("label");
                    if label.layout().line_count() != 1 {
                        problems2
                            .borrow_mut()
                            .push(format!("标签有 {} 行(应为 1)", label.layout().line_count()));
                    }

                    let view: gtk::ScrolledWindow =
                        find(window2.upcast_ref()).expect("label viewport");
                    if window2.width() > LABEL_MAX_WIDTH + CHROME_SLACK {
                        problems2.borrow_mut().push(format!(
                            "窗口宽 {} 超过上限 {LABEL_MAX_WIDTH}+{CHROME_SLACK}",
                            window2.width()
                        ));
                    }

                    let adj = view.hadjustment();
                    let end = (adj.upper() - adj.page_size()).max(adj.lower());
                    if adj.upper() > adj.page_size() + 0.5 && (adj.value() - end).abs() < 1.0 {
                        *scrolled2.borrow_mut() = true;
                    }
                });
                glib::ControlFlow::Continue
            }
        };
        glib::timeout_add_local(std::time::Duration::from_millis(150), tick);

        let finish = {
            let (problems, heights, widths, scrolled) = (
                problems.clone(),
                heights.clone(),
                widths.clone(),
                scrolled.clone(),
            );
            move || -> glib::ControlFlow {
                let heights = heights.borrow();
                let widths = widths.borrow();
                let mut problems = problems.borrow_mut();

                let distinct: BTreeSet<i32> = heights.iter().copied().collect();
                if distinct.len() > 1 {
                    problems.push(format!("高度出现多个取值: {distinct:?}(应恒定)"));
                }
                if !*scrolled.borrow() {
                    problems.push("文字溢出后没有滚到最右端".to_string());
                }
                if !widths.is_empty() && widths.iter().all(|w| *w <= *widths.first().unwrap()) {
                    problems.push("宽度没有随文字增长".to_string());
                }

                println!(
                    "scroll-check: 高度 {} -> {}",
                    heights.first().copied().unwrap_or(0),
                    heights.last().copied().unwrap_or(0)
                );
                println!(
                    "scroll-check: 宽度 {} -> {} (文本上限 {LABEL_MAX_WIDTH}px)",
                    widths.first().copied().unwrap_or(0),
                    widths.last().copied().unwrap_or(0)
                );
                println!("scroll-check: 滚到右端 = {}", scrolled.borrow());

                if problems.is_empty() {
                    println!("scroll-check: OK — 单行、高度恒定、宽度封顶、最新文字可见");
                    std::process::exit(0);
                }
                println!("scroll-check: {} 个问题", problems.len());
                for problem in problems.iter().take(8) {
                    println!("  - {problem}");
                }
                std::process::exit(1);
            }
        };
        glib::timeout_add_seconds_local(9, finish);
    });

    app.run();
}
