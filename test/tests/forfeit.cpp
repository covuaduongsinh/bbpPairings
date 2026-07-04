// Regression test: forfeit results are handled correctly -- a forfeit win
// ("+") counts as a win (1.0) and a forfeit loss ("-") as 0.0, and because a
// forfeited game was never actually played the two players remain eligible to
// be paired again. Pins the exact next-round pairing output.
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
