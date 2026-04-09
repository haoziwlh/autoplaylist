class Myplaylist < Formula
  desc "AI-powered music playlist generator and player"
  homepage "https://github.com/haoziwlh/autoplaylist"
  url "https://files.pythonhosted.org/packages/0d/17/f7ed833159c77816621cf68bfcb233e1a0a628888c74426bfdda9ea8302c/myplaylist-0.3.22-py3-none-any.whl",,,,,,,,,,,,,,,,,,,
      using: :nounzip
  sha256 "126ad2b1043a439a6edc474482c7a549e1190082c43ea4acfcdd0b5911949768"
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
