class Myplaylist < Formula
  desc "AI-powered music playlist generator and player"
  homepage "https://github.com/haoziwlh/autoplaylist"
  url "https://files.pythonhosted.org/packages/03/33/5f34a3ca2f2a797f74879f60caf9f6d5fb5928f0c37f5da63103f3de4924/myplaylist-0.3.8-py3-none-any.whl",,,,,,,,,,
      using: :nounzip
  sha256 "142d45648e167f6eb0b36c680bb1579791145f85779d3db070d36443dd8fae28"
  license "MIT"

  depends_on "python@3.11"
  depends_on "mpv"

  def install
    venv = libexec/"venv"
    system Formula["python@3.11"].opt_bin/"python3.11", "-m", "venv", venv
    system venv/"bin/pip", "install", "myplaylist==#{version}"
    bin.install_symlink venv/"bin/myplaylist"
  end

  test do
    assert_match "myplaylist", shell_output("#{bin}/myplaylist --help")
  end
end
