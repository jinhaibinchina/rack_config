# Graph Report - AppsManagers  (2026-11-09)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 6993 nodes · 15959 edges · 241 communities (101 shown, 140 thin omitted)
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 1362 edges (avg confidence: 0.88)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `6f771514`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8
- Community 9
- Community 10
- Community 11
- Community 12
- Community 13
- Community 14
- Community 15
- Community 16
- Community 17
- Community 18
- Community 19
- Community 20
- Community 21
- Community 22
- Community 23
- Community 24
- Community 25
- Community 26
- Community 27
- Community 28
- Community 29
- Community 30
- Community 31
- Community 32
- Community 33
- Community 34
- Community 35
- Community 36
- Community 37
- Community 38
- Community 39
- Community 40
- Community 41
- Community 42
- Community 43
- Community 44
- Community 45
- Community 46
- Community 47
- Community 48
- Community 49
- Community 50
- Community 51
- Community 52
- Community 53
- Community 54
- Community 55
- Community 57
- Community 58
- Community 60
- Community 61
- Community 62
- Community 63
- Community 64
- Community 65
- Community 66
- Community 67
- Community 68
- Community 69
- Community 70
- Community 71
- Community 72
- Community 73
- Community 74
- Community 75
- Community 76
- Community 77
- Community 78
- Community 79
- Community 80
- Community 81
- Community 82
- Community 83
- Community 84
- Community 85
- Community 86
- Community 87
- Community 88
- Community 89
- Community 90
- Community 91
- Community 92
- Community 93
- Community 94
- Community 95
- Community 96
- Community 97
- Community 98
- Community 99
- Community 100
- Community 101
- Community 102
- Community 103
- Community 104
- Community 105
- Community 106
- Community 107
- Community 108
- Community 109
- Community 110
- Community 111
- Community 112
- Community 115
- Community 116
- Community 117
- Community 118
- Community 120
- Community 122
- Community 123
- Community 125
- Community 126
- Community 127
- Community 128
- Community 129
- Community 130
- Community 131
- Community 132
- Community 133
- Community 134
- Community 135
- Community 136
- Community 137
- Community 138
- Community 139
- Community 142
- Community 143
- Community 144
- Community 145
- Community 146
- Community 147
- Community 148
- Community 149
- Community 150
- Community 151
- Community 152
- Community 153
- Community 154
- Community 155
- Community 156
- Community 157
- Community 158
- Community 159
- Community 160
- Community 161
- Community 164
- Community 166
- Community 167
- Community 170
- Community 171
- Community 172
- Community 173
- Community 174
- Community 175
- Community 177
- Community 179
- Community 180
- Community 182
- Community 183
- Community 184
- Community 186
- Community 188
- Community 190
- Community 191
- Community 193
- Community 194
- Community 196
- Community 197
- Community 200
- Community 202
- Community 203
- Community 204
- Community 208
- Community 209
- Community 210
- Community 211
- Community 212
- Community 215
- Community 216
- Community 217
- Community 218
- Community 219
- Community 221
- Community 222
- Community 223
- Community 224
- Community 225
- Community 226
- Community 227
- Community 228
- Community 229
- Community 231
- Community 232
- Community 233
- Community 234
- Community 235
- Community 236
- Community 237

## God Nodes (most connected - your core abstractions)
1. `base_element` - 154 edges
2. `QuadTreeScene` - 111 edges
3. `BaseItem` - 108 edges
4. `MplPlotWidget` - 108 edges
5. `GraphicsView` - 106 edges
6. `GraphicsScene` - 100 edges
7. `widget_element` - 83 edges
8. `DesignWindow` - 83 edges
9. `myGraphicsScene` - 81 edges
10. `NavigationContentWidget` - 75 edges

## Surprising Connections (you probably didn't know these)
- `RackGlobalParasWindow` --uses--> `QuadTreeScene`  [INFERRED]
  App_RackConfig/run/rack_global_paras_widget.py → Designer/Core/myQuadTreeScene.py
- `RackStoreWindow` --uses--> `QuadTreeScene`  [INFERRED]
  App_RackConfig/run/rack_store_widget.py → Designer/Core/myQuadTreeScene.py
- `main()` --uses--> `group_element`  [INFERRED]
  tools/verify_box_select.py → Designer/Core/elements.py
- `main()` --uses--> `rect_element`  [INFERRED]
  tools/verify_embedded_widget.py → Designer/Core/elements.py
- `RackStoresWindow` --uses--> `SceneMode`  [INFERRED]
  App_RackConfig/run/rack_stores_widget.py → Designer/Core/my_common.py

## Import Cycles
- 3-file cycle: `App_SafetyCar/__init__.py -> App_SafetyCar/safety_car_entry.py -> App_SafetyCar/ip_setup.py -> App_SafetyCar/__init__.py`
- 3-file cycle: `common/com/modbus/__init__.py -> common/com/modbus/modbus_data_broker.py -> common/com/modbus/modbus_plc_manager.py -> common/com/modbus/__init__.py`
- 4-file cycle: `Designer/Core/__init__.py -> Designer/Core/ui/__init__.py -> Designer/Core/ui/design_window_entry.py -> Designer/Core/element.py -> Designer/Core/__init__.py`
- 5-file cycle: `Designer/Core/__init__.py -> Designer/Core/ui/__init__.py -> Designer/Core/ui/design_window_entry.py -> Designer/Core/elements.py -> Designer/Core/element.py -> Designer/Core/__init__.py`
- 5-file cycle: `Designer/Core/__init__.py -> Designer/Core/ui/__init__.py -> Designer/Core/ui/design_window_entry.py -> Designer/Core/ui/template_store.py -> Designer/Core/element.py -> Designer/Core/__init__.py`
- 5-file cycle: `Designer/Core/__init__.py -> Designer/Core/ui/__init__.py -> Designer/Core/ui/design_window_entry.py -> Designer/Core/ui/element_factory.py -> Designer/Core/myQuadTreeScene.py -> Designer/Core/__init__.py`
- 5-file cycle: `Designer/Core/__init__.py -> Designer/Core/ui/__init__.py -> Designer/Core/ui/design_window_entry.py -> Designer/Core/ui/template_store.py -> Designer/Core/myQuadTreeScene.py -> Designer/Core/__init__.py`
- 5-file cycle: `Designer/Core/__init__.py -> Designer/Core/ui/__init__.py -> Designer/Core/ui/design_window_entry.py -> Designer/Core/ui/offline_run_dialog.py -> Designer/Core/myQuadTreeScene.py -> Designer/Core/__init__.py`
- 5-file cycle: `Designer/Core/__init__.py -> Designer/Core/ui/__init__.py -> Designer/Core/ui/design_window_entry.py -> Designer/Core/ui/design_page.py -> Designer/Core/myQuadTreeScene.py -> Designer/Core/__init__.py`
- 5-file cycle: `Designer/Core/NavigationContentWidget.py -> Designer/Core/myQuadTreeScene.py -> Designer/Core/__init__.py -> Designer/Core/ui/__init__.py -> Designer/Core/ui/design_window_entry.py -> Designer/Core/NavigationContentWidget.py`
- 5-file cycle: `Designer/Core/__init__.py -> Designer/Core/ui/__init__.py -> Designer/Core/ui/design_window_entry.py -> Designer/Core/ui/project_store.py -> Designer/Core/myQuadTreeScene.py -> Designer/Core/__init__.py`

## Communities (241 total, 140 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.04
Nodes (23): RackGlobalParasWindow, RackStoreWindow, is_group_element(), boolean_elements(), checkbox_element, group_element, get_boundRect_of_member(), polygon_element (+15 more)

### Community 1 - "Community 1"
Cohesion: 0.04
Nodes (16): main(), AGV_interact, main(), available_fonts(), make_banner(), LoadDialog, LoadMainWindow, LoadWidget (+8 more)

### Community 2 - "Community 2"
Cohesion: 0.03
Nodes (10): bit_index(), _display_width(), normalize_channel(), normalize_line(), normalize_module(), normalize_text_field(), _pad(), RackPanelStatus (+2 more)

### Community 4 - "Community 4"
Cohesion: 0.04
Nodes (7): GraphicsScene, SceneIndex, check(), close_rect(), main(), check_group_copy_z(), _variant_shot()

### Community 5 - "Community 5"
Cohesion: 0.04
Nodes (5): _norm_deg(), RuntimeCard, RuntimeSceneManager, RuntimeWidgetLayer, _trace()

### Community 6 - "Community 6"
Cohesion: 0.05
Nodes (5): norm_deg(), rotate_xy(), LineItem, PathItem, _PointBasedItem

### Community 7 - "Community 7"
Cohesion: 0.04
Nodes (3): RackHmiConfigModel, RackStoresWindow, RackStoresWindowV2

### Community 8 - "Community 8"
Cohesion: 0.05
Nodes (35): arp_map(), arp_prime(), _decode(), _default_gateways_linux(), find_devices(), get_interfaces(), get_primary_interface(), get_static_interfaces() (+27 more)

### Community 9 - "Community 9"
Cohesion: 0.04
Nodes (9): base_element, checkbox_element, circle_element, _color_text(), image_element, line_element, path_element, polygon_element (+1 more)

### Community 10 - "Community 10"
Cohesion: 0.05
Nodes (4): main(), PackagerThread, PythonPackager, SpecEditorDialog

### Community 11 - "Community 11"
Cohesion: 0.05
Nodes (29): attach_hmi_pages(), attach_hmi_pages(), make_page_specs(), as_bool(), loose_key(), norm_key(), PageSpec, TagCatalog (+21 more)

### Community 14 - "Community 14"
Cohesion: 0.06
Nodes (13): CheckboxPropertyItem, CirclePropertyItem, ImagePropertyItem, PathPropertyItem, PolygonPropertyItem, RectPropertyItem, TextPropertyItem, TrianglePropertyItem (+5 more)

### Community 15 - "Community 15"
Cohesion: 0.05
Nodes (20): _page_xy(), CheckboxItem, CircleItem, ImageItem, _load_pixmap(), PolygonItem, RectItem, _selection_overlay() (+12 more)

### Community 16 - "Community 16"
Cohesion: 0.07
Nodes (10): _fit_policy(), make_check(), make_double(), make_int(), make_line(), make_textarea(), ObjectHeader, color_str() (+2 more)

### Community 18 - "Community 18"
Cohesion: 0.05
Nodes (8): MultiMeta, LoadDialog, get_row_data_safe(), open_feather_reader(), time_it(), datetime_from_timestamp(), main(), set_bool()

### Community 19 - "Community 19"
Cohesion: 0.04
Nodes (11): time_it(), xLabelFormat, average_downsample_simple(), GlobalConfigSingleton, PlaySpeed, DynamicTickFormatter, FixedPositionLocator, xLabelFormat (+3 more)

### Community 20 - "Community 20"
Cohesion: 0.07
Nodes (5): _default_template_dir(), DesignerWindow, open_designer(), LayerTreeDock, attach()

### Community 21 - "Community 21"
Cohesion: 0.05
Nodes (5): MainWindow, QuadTreeScene, remove_parent_item(), check(), main()

### Community 23 - "Community 23"
Cohesion: 0.06
Nodes (16): compile_all(), iter_functions(), main(), module_stats(), resolve_hints(), _clean(), load_tags(), _safe_key() (+8 more)

### Community 24 - "Community 24"
Cohesion: 0.07
Nodes (13): OpcConfig, _fmt(), main(), NodeBrowser, walk(), collect(), entry_of(), expand() (+5 more)

### Community 27 - "Community 27"
Cohesion: 0.05
Nodes (11): base_element, checkbox_element, circle_element, _color_text(), group_element, image_element, path_element, polygon_element (+3 more)

### Community 29 - "Community 29"
Cohesion: 0.06
Nodes (17): _force_foreground(), main(), _MainThreadWatchdog, run(), _start_single(), _thread_stacks(), Tool, _tool() (+9 more)

### Community 30 - "Community 30"
Cohesion: 0.06
Nodes (9): PlotDataMapRef, combo_panel, custom_panel, text_to_pixmap_v1(), DataTransformer, replace_variable_dot(), ScriptDialog, ScriptInputDialog (+1 more)

### Community 31 - "Community 31"
Cohesion: 0.06
Nodes (8): PlotMatrixWithVice, IDataTranslater, RcdTr_for_polt_moudle, ComboPoltDialog, rcd_translater, _combo_entry(), _combo_plot(), _launcher_registration()

### Community 32 - "Community 32"
Cohesion: 0.07
Nodes (3): _ChangeHandler, _coerce(), OpcUaManager

### Community 34 - "Community 34"
Cohesion: 0.05
Nodes (12): CylinderState, describe_light(), describe_light_freq(), LightFreq, MaterialState, normalize_area(), normalize_cylinder_state(), normalize_light_freq() (+4 more)

### Community 35 - "Community 35"
Cohesion: 0.05
Nodes (15): _collect_tree_ids(), visit(), _read_point(), _shift_item_positions(), TemplateStore, _to_int(), ToolboxTemplate, ElementToolboxDock (+7 more)

### Community 36 - "Community 36"
Cohesion: 0.05
Nodes (4): rcd_data_bridge, IChartRenderer, IDataProvider, playerWorkerThread

### Community 37 - "Community 37"
Cohesion: 0.07
Nodes (4): ModbusClient, SignalBridge, TcpPositionWorker, Demo

### Community 38 - "Community 38"
Cohesion: 0.06
Nodes (11): CabinetPropertyItem, NavigationHost, build_station_page(), _expand_pages(), _normalize_lines(), StationCatalog, StationGroup, StationPage (+3 more)

### Community 40 - "Community 40"
Cohesion: 0.05
Nodes (5): datetime_from_timestamp(), string_to_datetime(), plot_window, SliderEventFilter, SplitterAnimator

### Community 41 - "Community 41"
Cohesion: 0.07
Nodes (26): _CGPoint, build_scene(), check(), close(), draw(), main(), run(), check() (+18 more)

### Community 42 - "Community 42"
Cohesion: 0.11
Nodes (6): _fmt(), make_hint(), make_label(), make_value_label(), PropertyPage, SectionCard

### Community 43 - "Community 43"
Cohesion: 0.09
Nodes (5): AxisMonitorPage, HmiPage, MainMonitorPage, ParameterSettingsPage, Card

### Community 45 - "Community 45"
Cohesion: 0.05
Nodes (5): ClickableQLabel, rcd_panel, rcd_panel_filter, rcd_panel_tips, TreeWigdetEventFilter

### Community 46 - "Community 46"
Cohesion: 0.08
Nodes (4): _as_pixel_size(), HmiClient, HmiPagesHost, factory()

### Community 48 - "Community 48"
Cohesion: 0.05
Nodes (10): check(), close_rect(), main(), grid_gap(), _has_label(), _is_white(), off_grid(), _scan_rect() (+2 more)

### Community 50 - "Community 50"
Cohesion: 0.07
Nodes (8): EmbeddedWidgetLayer, main(), ProbeLineEdit, ProbeWindow, _run_selftest(), _run_shots(), step(), SceneCanvas

### Community 51 - "Community 51"
Cohesion: 0.06
Nodes (11): _data_type_id(), _main(), _make_struct_type(), MockOpcUaServer, _pack_struct(), check(), _LogCapture, main() (+3 more)

### Community 52 - "Community 52"
Cohesion: 0.08
Nodes (16): AlarmPage, setter(), setter(), IoMonitorPage, take_in(), take_out(), setter(), LogPage (+8 more)

### Community 53 - "Community 53"
Cohesion: 0.11
Nodes (8): _builtin_type(), is_builtin_datatype(), _nid_key(), _ns_of(), _short(), _short_list(), StructField, StructureReader

### Community 54 - "Community 54"
Cohesion: 0.06
Nodes (6): Ui_Dialog, safety_paramsters, station_status_query, DataBroker, PollingThread, time_it()

### Community 57 - "Community 57"
Cohesion: 0.25
Nodes (3): ParseError, Parser, _tok_desc()

### Community 62 - "Community 62"
Cohesion: 0.07
Nodes (6): LogicScriptInputDialog, LogicalDataGenerator, LogicalScriptDialog, replace_variable_dot(), test_logical_generator(), _logic_dialog()

### Community 65 - "Community 65"
Cohesion: 0.08
Nodes (4): debug_log(), SnapInfo, SnapSystem, warp_cursor()

### Community 67 - "Community 67"
Cohesion: 0.06
Nodes (7): AGV_interact, HmiConfig, RackStorage, Rcd, Recipe, get_bool(), get_int()

### Community 68 - "Community 68"
Cohesion: 0.08
Nodes (6): RackGlobalParasModelV2, _demo(), RackGlobalParasWindowV2, check(), FakePlc, main()

### Community 70 - "Community 70"
Cohesion: 0.08
Nodes (3): SafetySceneView, check(), main()

### Community 71 - "Community 71"
Cohesion: 0.08
Nodes (7): add_child_item(), default_name_args(), free_name(), name_in_use(), next_default_name(), rename_members(), DesignScene

### Community 74 - "Community 74"
Cohesion: 0.10
Nodes (29): AssignStmt, ASTNode, BreakStmt, CallStmt, ContinueStmt, _default_profile(), DelayStmt, DeviceProfile (+21 more)

### Community 75 - "Community 75"
Cohesion: 0.07
Nodes (12): main(), open_designer(), make_render(), _render(), fn(), build(), main(), load_old() (+4 more)

### Community 76 - "Community 76"
Cohesion: 0.12
Nodes (19): is_standard_subtree(), flatten(), build_subscription_map(), _fmt_value(), _looks_like_struct(), main(), NodeInfo, print_table() (+11 more)

### Community 78 - "Community 78"
Cohesion: 0.11
Nodes (4): DesignArea, MainWindow, ToolboxWidget, ToolButton

### Community 80 - "Community 80"
Cohesion: 0.23
Nodes (23): OpCode, RobotFormatter, RobotParser, VarSymbol, check(), expect_error(), test_basic(), test_conditions() (+15 more)

### Community 81 - "Community 81"
Cohesion: 0.09
Nodes (3): FlipDigit, FlipDigit_bottom, FlipDigit_top

### Community 82 - "Community 82"
Cohesion: 0.09
Nodes (4): _axis_scale(), image_element, _resize_anchor_local(), _scale_about()

### Community 83 - "Community 83"
Cohesion: 0.08
Nodes (19): set_enabled(), bench(), bench_ab(), breakdown(), breakdown_ab(), breakdown_cases(), bbox_loop(), bookkeeping() (+11 more)

### Community 84 - "Community 84"
Cohesion: 0.07
Nodes (6): SourceMap, LineNumberArea, main(), PointEditorDialog, PREditorDialog, RobotHighlighter

### Community 85 - "Community 85"
Cohesion: 0.15
Nodes (9): group_element, rect_element, text_element, triangle_element, read_wstring(), _is_text_like(), normalize_light(), sensor_index_of() (+1 more)

### Community 86 - "Community 86"
Cohesion: 0.10
Nodes (4): AsciiPanel, BannerStyle, build_rows(), main()

### Community 87 - "Community 87"
Cohesion: 0.08
Nodes (9): GroupPropertyItem, apply_visibility(), current_member(), sync_fields(), check(), _FakeManager, _FakeScene, main() (+1 more)

### Community 88 - "Community 88"
Cohesion: 0.08
Nodes (4): GroupItem, SceneProjection, load_page(), projection_from()

### Community 89 - "Community 89"
Cohesion: 0.12
Nodes (13): create_control(), _css_color(), normalize_variant(), paint_variant(), _tri(), widget_display_text(), widget_field(), _widget_font() (+5 more)

### Community 90 - "Community 90"
Cohesion: 0.14
Nodes (4): TagRef, _pixel_font(), _root(), TagValue

### Community 92 - "Community 92"
Cohesion: 0.08
Nodes (6): battery, label_checkbutton_out, my_checkbutton, my_text_comboBox, my_text_value, my_text_value_editable

### Community 95 - "Community 95"
Cohesion: 0.13
Nodes (7): brush_for(), _color_key(), dashed_pen_for(), font_for(), _new_dashed_pen(), pen_for(), test_paint_cache()

### Community 98 - "Community 98"
Cohesion: 0.09
Nodes (3): ConfirmBar, ElidedLabel, PageHeader

### Community 100 - "Community 100"
Cohesion: 0.10
Nodes (9): install_quiet_reconnect(), install_reconnect_diagnostics(), is_writable(), _ReconnectNoiseFilter, _ReconnectTraceFilter, _release_orphan(), _unwrap(), is_struct_value() (+1 more)

### Community 102 - "Community 102"
Cohesion: 0.12
Nodes (4): _cancel_publish_loop(), keep_alive_until_stopped(), DemoWindow, main()

### Community 107 - "Community 107"
Cohesion: 0.11
Nodes (3): Rcd, PLCManager, HeartbeatThread

### Community 108 - "Community 108"
Cohesion: 0.10
Nodes (9): RackConfigWindow, convert_with_error_handling(), RcdWindow, _make_designer(), _make_log_plot(), _make_motion_editer(), _make_pop_pick(), _make_rack() (+1 more)

### Community 110 - "Community 110"
Cohesion: 0.10
Nodes (5): check(), main(), main_chain_imports(), wait(), wait_finished()

### Community 112 - "Community 112"
Cohesion: 0.13
Nodes (3): IoLamp, nearest_light_color(), LightColor

### Community 115 - "Community 115"
Cohesion: 0.10
Nodes (7): check(), main(), make_widget_element(), _report(), StubLayer, StubScene, StubView

### Community 116 - "Community 116"
Cohesion: 0.11
Nodes (5): _coerce(), IndicatorGrid, Lamp, _same_state(), WritableValue

### Community 120 - "Community 120"
Cohesion: 0.17
Nodes (6): _c(), _fmt_num(), Instruction, PeepholeOptimizer, _t(), _v()

### Community 122 - "Community 122"
Cohesion: 0.11
Nodes (5): Page0_Model, Page1_Model, Page3_Model, _PlcBackendMixin, Recipe

### Community 123 - "Community 123"
Cohesion: 0.11
Nodes (3): cabinet_status_data, IO_data, plc_safety

### Community 128 - "Community 128"
Cohesion: 0.18
Nodes (7): JsonTagClient, main(), _parse_value(), _pump(), _wait_connected(), check(), main()

### Community 131 - "Community 131"
Cohesion: 0.11
Nodes (3): AxisLine, DirtyRegionManager, watch_dog

### Community 132 - "Community 132"
Cohesion: 0.10
Nodes (3): visit(), _template_int(), _template_point()

### Community 133 - "Community 133"
Cohesion: 0.16
Nodes (12): build(), build_structure_index(), collect_members(), dimension(), documentation(), lname(), loose_key(), main() (+4 more)

### Community 134 - "Community 134"
Cohesion: 0.11
Nodes (11): check(), _hit_point(), _pose_equal(), _rect_equal(), _report(), run(), _click_probe_button(), _click_widget_button() (+3 more)

### Community 135 - "Community 135"
Cohesion: 0.15
Nodes (3): AsciiArtPanel, _classify(), main()

### Community 136 - "Community 136"
Cohesion: 0.11
Nodes (8): check(), _FakeAction, _FakeStatusBar, _FakeWindow, main(), box(), clear_selection(), refresh_panel()

### Community 139 - "Community 139"
Cohesion: 0.11
Nodes (5): int_to_hex(), get_err_info(), system_status_data, Ui_safety_display, Ui_Form

### Community 150 - "Community 150"
Cohesion: 0.20
Nodes (9): build_window(), cmd_costs(), cmd_frames(), cmd_idle(), cmd_stress(), counters(), main(), PaintCounter (+1 more)

### Community 151 - "Community 151"
Cohesion: 0.17
Nodes (9): check(), fmt(), main(), make_rect(), make_text(), make_triangle(), near(), _report() (+1 more)

### Community 154 - "Community 154"
Cohesion: 0.18
Nodes (3): ToolDefinition, ElementToolButton, TemplateToolButton

### Community 157 - "Community 157"
Cohesion: 0.18
Nodes (3): _button_min_hint(), MomentaryButton, PulseButton

### Community 159 - "Community 159"
Cohesion: 0.14
Nodes (4): _install_central_widget(), load_ui(), LoadWidget, _UiLoader

### Community 161 - "Community 161"
Cohesion: 0.21
Nodes (3): _read_point(), _shift_item_positions(), TemplateStore

### Community 164 - "Community 164"
Cohesion: 0.29
Nodes (11): BinOpExpr, ConstExpr, DistanceToExpr, Expr, expr_var_refs(), GetDIExpr, GetDOExpr, GetOverallExpr (+3 more)

### Community 166 - "Community 166"
Cohesion: 0.16
Nodes (6): add_zValue_group(), handle_go_bottom(), get_max_zValue_in_group(), handle_go_top(), get_min_zValue_in_group(), set_group_zValue()

### Community 167 - "Community 167"
Cohesion: 0.23
Nodes (6): best_of(), main(), PaintCounter, run_swap(), set_zoom(), spin()

### Community 171 - "Community 171"
Cohesion: 0.35
Nodes (8): AndCondition, CmpCondition, Condition, ConstCondition, _eval_const_cmp(), fold_condition(), NotCondition, OrCondition

### Community 174 - "Community 174"
Cohesion: 0.26
Nodes (5): _create_template_icon(), _create_tool_icon(), _dict_point(), _safe_float(), _template_bounds()

### Community 175 - "Community 175"
Cohesion: 0.26
Nodes (9): create_template_instance(), assign_ids(), visit(), _find_root_data(), _instance_item_name(), _sorted_children(), _source_z_value(), _to_int() (+1 more)

### Community 177 - "Community 177"
Cohesion: 0.17
Nodes (5): check(), _FakeClient, _FakeDataTypeNode, _struct_def(), test_decoder()

### Community 196 - "Community 196"
Cohesion: 0.25
Nodes (3): handle_return(), transfer_ip(), IPChangeWorker

### Community 203 - "Community 203"
Cohesion: 0.29
Nodes (3): _close_trace(), _DeferredNativeClose, _is_native_window_close()

## Knowledge Gaps
- **140 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TabbedPlotWidget` connect `Community 25` to `Community 36`, `Community 40`, `Community 19`, `Community 61`, `Community 31`?**
  _High betweenness centrality (0.057) - this node is a cross-community bridge._
- **Are the 6 inferred relationships involving `base_element` (e.g. with `Transform` and `DesignScene`) actually correct?**
  _`base_element` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.03984980620155039 - nodes in this community are weakly interconnected._
- **Why does `base_element` connect `Community 28` to `Community 0`, `Community 192`, `Community 230`, `Community 71`, `Community 140`, `Community 141`, `Community 237`, `Community 175`, `Community 113`, `Community 17`, `Community 214`, `Community 119`, `Community 154`, `Community 220`, `Community 93`, `Community 191`?**
  _High betweenness centrality (0.054) - this node is a cross-community bridge._
- **Are the 24 inferred relationships involving `QuadTreeScene` (e.g. with `RackGlobalParasWindow` and `RackStoreWindow`) actually correct?**
  _`QuadTreeScene` has 24 INFERRED edges - model-reasoned connections that need verification._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.0372453443319585 - nodes in this community are weakly interconnected._
- **Why does `GraphicsView` connect `Community 49` to `Community 1`, `Community 195`, `Community 70`, `Community 103`, `Community 75`, `Community 77`, `Community 79`, `Community 48`, `Community 114`, `Community 20`, `Community 85`, `Community 56`, `Community 121`, `Community 27`?**
  _High betweenness centrality (0.045) - this node is a cross-community bridge._