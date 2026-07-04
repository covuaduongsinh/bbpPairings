// Regression test: a half-point bye ("0000 - H") is scored as 0.5, placing the
// player in their own score group between the winners (1.0) and losers (0.0),
// and the next round is paired accordingly. Pins the exact pairing output.
void TEST_FUNCTION(const testing::Context &context)
{
  auto output_filename = STRINGIFY(TEST_ID) ".output";
  testing::run(
    context.exe_path.string()
    + " --dutch "
    + (context.data_folder_path / STRINGIFY(TEST_ID) ".input").string()
    + " -p "
    + output_filename);
  testing::assert_file_content_matches(
    context.data_folder_path / output_filename,
    context.data_folder_path / STRINGIFY(TEST_ID) ".output.expected");
}
