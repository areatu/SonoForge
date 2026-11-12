"""The declared public inspection surface of ``ViewerWidget`` (issue 327).

``ViewerWidget`` is a ~10 000-line class with 236 private attributes and 307
private helpers.  Its tests used to read and write those members directly --
672 scattered ``w._name`` references in ten files -- so any attempt to split the
widget broke hundreds of tests that asserted nothing about behaviour.

``ViewerContract`` is the single, *declared* seam that replaces them.  A test
writes ``w.contract.play_button.text()`` or ``w.contract.update_levels()``
instead of ``w._play_button.text()`` / ``w._update_levels()``; the adapter maps
that name onto the widget's private member in one place.  Reads, writes and
private-method calls all go through the same allowlist:

* ``__getattr__`` returns ``getattr(viewer, "_" + name)`` -- for a method that
  is the bound method, so ``w.contract.refresh_frame_overlay()`` works;
* ``__setattr__`` writes ``setattr(viewer, "_" + name, value)``, so arrangement
  code such as ``w.contract.calibration_active = True`` still works;
* an unknown name raises ``AttributeError`` instead of silently reaching into
  the widget.

This is deliberately a *compatibility seam*, not a design approval: the names
below are exactly the private members the tests used at the time of the slice,
frozen in ``tests/architecture/viewer_contract_allowlist.json``.  Adding one
requires a reviewed change to that file (``test_viewer_contract_api.py`` fails
otherwise).  Decomposition of ``ViewerWidget`` now touches this one adapter
instead of hundreds of call sites, and the ``check_test_private_access.py``
ratchet keeps the test side at zero.

The six methods that tests patch with ``patch.object`` were promoted to real
public methods on ``ViewerWidget`` instead of being routed through the adapter:
patching an adapter wrapper would not intercept calls the widget makes to
``self.<method>()``.  They are listed in the allowlist as ``promoted``.
"""

from __future__ import annotations

from typing import Any

#: Every private member exposed through the seam. Frozen by the architecture
#: test; do not add a name without a reviewed allowlist change.
EXPOSED_PRIVATE_NAMES = frozenset(
    {
        "_active_arc_points",
        "_active_caliper_label_item",
        "_active_contour_chamber",
        "_active_contour_phase",
        "_active_contour_view",
        "_active_mitral_annulus",
        "_active_mitral_septal",
        "_append_rendered_contour",
        "_apply_caliper_node_drag",
        "_apply_magnetic_snap_to_contour",
        "_apply_optical_flow_refinement",
        "_apply_rbf_drag_step",
        "_apply_window_level_preferences",
        "_auto_snap_new_contour",
        "_begin_caliper_node_drag",
        "_cached_levels_key",
        "_calibration_active",
        "_calibration_h_guide_end_item",
        "_calibration_h_guide_start_item",
        "_calibration_kind",
        "_calibration_line_item",
        "_calibration_marker_item",
        "_calibration_start_y",
        "_caliper_drag_active",
        "_caliper_label_index",
        "_caliper_labels",
        "_caliper_line_width",
        "_caliper_pen",
        "_caliper_sequence",
        "_clear_active_contour_drawing",
        "_clear_calibration_caliper",
        "_clear_calibration_graphics",
        "_clear_contour_hover",
        "_clear_contour_node_highlights",
        "_clear_crosshair",
        "_clear_drag_session",
        "_clear_ghost_overlay",
        "_clear_linear_caliper",
        "_clear_linear_caliper_graphics",
        "_clear_panel_frame_graphics",
        "_clear_rendered_contours",
        "_color_source_rgb",
        "_compute_hover_target",
        "_constrain_linear_endpoint",
        "_contour_editing_blocked",
        "_contour_frame_index",
        "_contour_items",
        "_contour_mode_active",
        "_contour_mode_kind",
        "_contour_pen_ai",
        "_contour_pen_for",
        "_contour_pen_ma",
        "_contour_pen_manual",
        "_contour_pen_model",
        "_contour_stage",
        "_contour_xy",
        "_create_contour_render",
        "_crosshair_h_item",
        "_crosshair_panel_bounds",
        "_crosshair_v_item",
        "_current_caliper_label",
        "_current_frame",
        "_current_instance_metadata",
        "_current_state",
        "_debug_overlay_label",
        "_debug_overlay_visible",
        "_debug_roi_item",
        "_delete_selected_caliper",
        "_dr_slider",
        "_drag_session",
        "_draw_debug_roi_rect",
        "_ecg_strip",
        "_effective_display_levels",
        "_emit_pending_scroll",
        "_emit_stored_linear_measurements",
        "_ensure_calibration_horizontal_guides",
        "_ensure_crosshair_graphics",
        "_external_wl_dr_sliders",
        "_find_stored_contour_index",
        "_finish_caliper_node_drag",
        "_finish_manual_contour",
        "_fps_label",
        "_frame_overlay_lines",
        "_frame_panel_layout",
        "_frame_panels_from_dicom",
        "_freehand_open_arc",
        "_freehand_points",
        "_freehand_recording",
        "_get_fusion_result",
        "_get_last_segment_roi",
        "_ghost_items",
        "_graphics",
        "_handle_calibration_mouse_press",
        "_handle_caliper_drag_release",
        "_handle_contour_drag_release",
        "_handle_contour_drag_release_from_global",
        "_handle_contour_hover",
        "_handle_contour_zone_drag",
        "_handle_contour_zone_press",
        "_handle_contour_zone_release",
        "_handle_ctrl_wheel",
        "_handle_wheel",
        "_hint_bar",
        "_hover_contour_index",
        "_hover_grab_index",
        "_image_item",
        "_image_smooth",
        "_is_color_frame",
        "_is_levels_outlier",
        "_last_drag_apply_pos",
        "_last_view_cursor_xy",
        "_length_display_unit",
        "_level_slider",
        "_levels_sliders_key",
        "_linear_caliper_active",
        "_linear_caliper_line_item",
        "_linear_caliper_marker_item",
        "_linear_caliper_start",
        "_linear_measurement_from_endpoints",
        "_linear_measurement_key",
        "_load_ecg_for_strip",
        "_map_view_event",
        "_mark_results_overlay_custom_position",
        "_measurement_crosshair_active",
        "_measurement_label",
        "_on_la_assist_contour_ready",
        "_on_optical_flow_refined",
        "_on_results_overlay_clear",
        "_on_results_overlay_pin_toggled",
        "_on_results_overlay_reset_position",
        "_on_ste_smoothness_changed",
        "_on_timeline_changed",
        "_overlay_label",
        "_panel_frame_items",
        "_pending_scroll_index",
        "_phi_filter",
        "_pinned_indices_for_contour",
        "_pixel_spacing_for_linear_label",
        "_play_button",
        "_position_overlay_labels",
        "_position_vessel_sensitivity_overlay",
        "_rbf_highlight_color",
        "_rebuild_contour_pens",
        "_refresh_caliper_line_pens",
        "_refresh_frame_overlay",
        "_refresh_frame_overlays",
        "_refresh_frame_panel_layout",
        "_refresh_panel_frame_graphics",
        "_refresh_rendered_contour_pens",
        "_refresh_speckle_overlay_for_current_frame",
        "_reindex_contour_nodes",
        "_render_contours_for_current_frame",
        "_render_ghost_overlay",
        "_resolve_contour_phase",
        "_resolve_display_mode",
        "_resolve_frame_panels",
        "_results_overlay_label",
        "_save_current_wl_dr",
        "_save_viewer_image",
        "_scroll_debounce_ms",
        "_set_caliper_label",
        "_set_contour_nodes_pickable",
        "_set_image_smooth",
        "_set_wl_dr_sliders",
        "_show_caliper_inline_labels",
        "_show_caliper_labels_on_frame",
        "_show_crosshair",
        "_show_panel_frames",
        "_source_label",
        "_speckle_overlay",
        "_speckle_result",
        "_step_back",
        "_step_forward",
        "_stored_contours",
        "_stored_linear_measurements",
        "_syncing_state",
        "_tag_contour_instance",
        "_timeline_slider",
        "_update_calibration_horizontal_guides",
        "_update_caliper_label_graphics",
        "_update_contour_hover",
        "_update_contour_node_highlights",
        "_update_debug_overlay",
        "_update_levels",
        "_update_measurement_crosshair",
        "_update_timeline_indicator",
        "_upsert_stored_contour",
        "_vertical_caliper_labels",
        "_vessel_sensitivity",
        "_view",
        "_view_metrics_for_rbf",
        "_window_slider",
        "_zone_drag_active",
        "_zoom_loupe_click",
        "_zoom_loupe_hint",
    }
)


class ViewerContract:
    """One named adapter between viewer tests and ``ViewerWidget`` internals."""

    __slots__ = ("_viewer",)

    def __init__(self, viewer: Any) -> None:
        object.__setattr__(self, "_viewer", viewer)

    def __getattr__(self, name: str) -> Any:
        private = "_" + name
        if private in EXPOSED_PRIVATE_NAMES:
            return getattr(self._viewer, private)
        raise AttributeError(f"ViewerContract has no member {name!r}; add it to the reviewed allowlist")

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_viewer":
            object.__setattr__(self, name, value)
            return
        private = "_" + name
        if private in EXPOSED_PRIVATE_NAMES:
            setattr(self._viewer, private, value)
            return
        raise AttributeError(f"ViewerContract has no member {name!r}; add it to the reviewed allowlist")
