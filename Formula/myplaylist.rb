class Myplaylist < Formula
  desc "AI-powered music playlist generator and player"
  homepage "https://github.com/haoziwlh/autoplaylist"
  url "https://files.pythonhosted.org/packages/6e/71/3730c99f75eb212149d643ece0c31088c9d02a45480c61ef933d49125bd2/myplaylist-0.3.24-py3-none-any.whl",,,,,,,,,,,,,,,,,,,,,
      using: :nounzip
  sha256 "b53886c0869b652897423f6ab618c1cbefaf98bcd53532132ac2690ea276aeaa"
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
